from django.db import migrations


FIELDS = ('contrato_id', 'evento_id', 'os_id', 'bm_id', 'valor_pago', 'parcela_paga',
    'data_pagamento', 'arquivo_nf', 'observacao', 'financeiro_autorizou', 'nf_dentro_prazo',
    'numero_nf', 'serie', 'data_emissao', 'chave_acesso', 'tipo_documento', 'comprovante_pagamento')


def snapshot(side):
    pairs = []
    for field in FIELDS:
        pairs.extend([f"'{field}'", f'{side}.{field}'])
    for key, expression in (
        ('bm_numero', f'(SELECT numero_bm FROM gestao_contratos_bm WHERE id={side}.bm_id)'),
        ('bm_valor_medido', f'(SELECT valor_pago FROM gestao_contratos_bm WHERE id={side}.bm_id)'),
        ('bm_operacional_lider', f'(SELECT status_coordenador FROM gestao_contratos_bm WHERE id={side}.bm_id)'),
        ('bm_operacional_gerente', f'(SELECT status_gerente FROM gestao_contratos_bm WHERE id={side}.bm_id)'),
        ('bm_diretoria', f'(SELECT aprovacao_pagamento FROM gestao_contratos_bm WHERE id={side}.bm_id)'),
        ('bm_data_autorizacao', f'(SELECT data_aprovacao_diretor FROM gestao_contratos_bm WHERE id={side}.bm_id)'),
    ):
        pairs.extend([f"'{key}'", expression])
    return 'json_object(' + ','.join(pairs) + ')'


def create(apps, schema_editor):
    if schema_editor.connection.vendor != 'sqlite':
        raise RuntimeError('Fase 3: trilha validada para SQLite; preparar DDL equivalente antes de outro banco.')
    ctx = lambda key: f"json_extract(hidro_financial_context(),'$.{key}')"
    changed = ' OR '.join(f'OLD.{field} IS NOT NEW.{field}' for field in FIELDS)
    schema_editor.execute('''CREATE TRIGGER hidro_nf_requires_bm BEFORE INSERT ON gestao_contratos_nf
        WHEN NEW.bm_id IS NULL BEGIN SELECT RAISE(ABORT,'Nova NF exige BM.'); END''')
    valid_payment='''EXISTS(SELECT 1 FROM gestao_contratos_bm b
        LEFT JOIN gestao_contratos_evento e ON e.id=b.evento_id
        LEFT JOIN gestao_contratos_os o ON o.id=b.os_id
        WHERE b.id=NEW.bm_id AND b.aprovacao_pagamento='aprovado'
        AND (b.status_coordenador='aprovado' OR b.status_gerente='aprovado')
        AND b.status_coordenador!='reprovado' AND b.status_gerente!='reprovado'
        AND coalesce(b.evento_id,0)=coalesce(NEW.evento_id,0) AND coalesce(b.os_id,0)=coalesce(NEW.os_id,0)
        AND ((b.evento_id IS NOT NULL AND b.os_id IS NULL AND e.contrato_terceiro_id=NEW.contrato_id)
          OR (b.os_id IS NOT NULL AND b.evento_id IS NULL AND o.contrato_id=NEW.contrato_id AND b.contrato_id=NEW.contrato_id AND o.status!='cancelada')))'''
    for action in ('INSERT','UPDATE'):
        schema_editor.execute(f'''CREATE TRIGGER hidro_nf_authorized_{action.lower()} BEFORE {action} ON gestao_contratos_nf
            WHEN NEW.financeiro_autorizou=1 AND {ctx('autor_grupo')}='financeiro' AND NOT ({valid_payment})
            BEGIN SELECT RAISE(ABORT,'Pagamento exige origem válida e autorização operacional/Diretoria.'); END''')
    schema_editor.execute(f'''CREATE TRIGGER hidro_nf_paid_reason BEFORE UPDATE ON gestao_contratos_nf
        WHEN OLD.financeiro_autorizou=1 AND ({changed}) BEGIN
        SELECT CASE WHEN coalesce({ctx('justificativa')},'')='' THEN RAISE(ABORT,'Justificativa obrigatória para correção de NF paga.') END;
        SELECT CASE WHEN {ctx('autor_grupo')}='financeiro' THEN RAISE(ABORT,'NF paga somente leitura para Financeiro.') END;
        END''')
    schema_editor.execute(f'''CREATE TRIGGER hidro_nf_delete_reason BEFORE DELETE ON gestao_contratos_nf
        WHEN OLD.financeiro_autorizou=1 BEGIN
        SELECT CASE WHEN coalesce({ctx('justificativa')},'')='' THEN RAISE(ABORT,'Justificativa obrigatória para exclusão de NF paga.') END;
        SELECT CASE WHEN {ctx('autor_grupo')}='financeiro' THEN RAISE(ABORT,'NF paga somente leitura para Financeiro.') END;
        END''')
    for action, side, previous, following, operation, condition in (
        ('INSERT','NEW','NULL',snapshot('NEW'),"'criacao'",''),
        ('UPDATE','NEW',snapshot('OLD'),snapshot('NEW'),
         "CASE WHEN OLD.financeiro_autorizou=0 AND NEW.financeiro_autorizou=1 THEN 'pagamento' WHEN OLD.financeiro_autorizou=1 AND NEW.financeiro_autorizou=0 THEN 'desmarcacao' WHEN OLD.financeiro_autorizou=1 THEN 'correcao_paga' ELSE 'alteracao' END",f'WHEN {changed}'),
        ('DELETE','OLD',snapshot('OLD'),'NULL',"'exclusao'",''),
    ):
        description = "'Exclusão da NF #'" if action=='DELETE' else "'Cadastro da NF #'" if action=='INSERT' else "'Edição da NF #'"
        details = f"{description} || {side}.id"
        if action=='UPDATE':
            details += " || '; paga anteriormente: ' || CASE WHEN OLD.financeiro_autorizou=1 THEN 'sim' ELSE 'não' END || '; pagamento realizado após edição: ' || CASE WHEN NEW.financeiro_autorizou=1 THEN 'sim.' ELSE 'não.' END"
        schema_editor.execute(f'''CREATE TRIGGER hidro_nf_audit_{action.lower()} AFTER {action} ON gestao_contratos_nf {condition}
            BEGIN INSERT INTO gestao_contratos_registroauditoria
            (content_type_id,object_id,acao,usuario_id,modelo,representacao_objeto,detalhes,data_hora,
             operacao_financeira,estado_anterior,estado_posterior,justificativa,autor_nome,autor_grupo)
            VALUES ((SELECT id FROM django_content_type WHERE app_label='gestao_contratos' AND model='nf'),
             {side}.id, '{'criado' if action=='INSERT' else 'atualizado'}', {ctx('usuario_id')}, 'NF', 'NF #' || {side}.id,
             {details},strftime('%Y-%m-%d %H:%M:%f','now'),{operation},{previous},{following},
             {ctx('justificativa')},{ctx('autor_nome')},{ctx('autor_grupo')}); END''')
    for action in ('UPDATE','DELETE'):
        schema_editor.execute(f'''CREATE TRIGGER hidro_financial_audit_no_{action.lower()}
            BEFORE {action} ON gestao_contratos_registroauditoria
            WHEN OLD.operacao_financeira IS NOT NULL BEGIN
            SELECT RAISE(ABORT,'Histórico financeiro permanente: alteração ou exclusão proibida.'); END''')


def remove(apps, schema_editor):
    for name in ('hidro_nf_paid_reason','hidro_nf_delete_reason','hidro_nf_audit_insert',
                 'hidro_nf_audit_update','hidro_nf_audit_delete','hidro_financial_audit_no_update','hidro_financial_audit_no_delete',
                 'hidro_nf_requires_bm','hidro_nf_authorized_insert','hidro_nf_authorized_update'):
        schema_editor.execute(f'DROP TRIGGER IF EXISTS {name}')


class Migration(migrations.Migration):
    dependencies = [('gestao_contratos','0117_nf_fiscal_auditoria_financeira')]
    operations = [migrations.RunPython(create, remove)]
