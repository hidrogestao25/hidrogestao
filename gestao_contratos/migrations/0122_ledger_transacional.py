"""DDL congelada SQLite: liquidações exatas, append-only e compatibilidade NF."""
from importlib import import_module
from django.db import migrations

P='gestao_contratos_pagamentonf'
S='gestao_contratos_programacaopagamento'
A='gestao_contratos_reprogramacaopagamento'
N='gestao_contratos_nf'
R='gestao_contratos_registroauditoria'
CTX=lambda key:f"json_extract(hidro_financial_context(),'$.{key}')"
MODE=lambda key:f"coalesce(json_extract(hidro_ledger_mode(),'$.{key}'),0)"
NET=lambda nf:f"coalesce((SELECT sum(CASE tipo WHEN 'estorno' THEN -centavos ELSE centavos END) FROM {P} WHERE nf_id={nf}),0)"
CENT=lambda value:f'CAST(round(({value})*100) AS INTEGER)'


def root_snapshot(nf,extras=()):
    pairs=[]
    for field in ('contrato_id','evento_id','os_id','bm_id','valor_pago','numero_nf','financeiro_autorizou','vencimento_original','cancelada_em'):
        pairs.extend([f"'{field}'",'n.'+field])
    for key,expr in extras:pairs.extend([f"'{key}'",expr])
    for key,column in (('bm_numero','numero_bm'),('bm_operacional_lider','status_coordenador'),('bm_operacional_gerente','status_gerente'),('bm_diretoria','aprovacao_pagamento'),('bm_data_autorizacao','data_aprovacao_diretor'),('bm_valor_medido','valor_pago')):
        pairs.extend([f"'{key}'",f'(SELECT {column} FROM gestao_contratos_bm WHERE id=n.bm_id)'])
    pairs.extend(["'liquidado_centavos'",NET('n.id')])
    return f"(SELECT json_object({','.join(pairs)}) FROM {N} n WHERE n.id={nf})"


def audit_insert(table,label,operation,snapshot,condition='',before='NULL'):
    return f'''CREATE TRIGGER hidro_{label}_audit_insert AFTER INSERT ON {table} {condition} BEGIN
      INSERT INTO {R}(content_type_id,object_id,acao,usuario_id,modelo,representacao_objeto,detalhes,data_hora,operacao_financeira,estado_anterior,estado_posterior,justificativa,autor_nome,autor_grupo)
      VALUES((SELECT id FROM django_content_type WHERE app_label='gestao_contratos' AND model='nf'),NEW.nf_id,'criado',{CTX('usuario_id')},'{label}','NF #'||NEW.nf_id,'{label} #'||NEW.id,strftime('%Y-%m-%d %H:%M:%f','now'),{operation},{before},{snapshot},{CTX('justificativa')},{CTX('autor_nome')},{CTX('autor_grupo')}); END'''


def create(apps,editor):
    if editor.connection.vendor!='sqlite':raise RuntimeError('Ledger Fase 5 exige DDL equivalente homologada para este motor.')
    execute=editor.execute
    old=import_module('gestao_contratos.migrations.0118_trilha_nf_transacional')
    fields=(*old.FIELDS,'vencimento_original','cancelada_em','cancelada_por_id','motivo_cancelamento')
    changed=' OR '.join(f'OLD.{f} IS NOT NEW.{f}' for f in fields)
    content_changed=' OR '.join(f'OLD.{f} IS NOT NEW.{f}' for f in fields if f!='financeiro_autorizou')
    for name in ('hidro_nf_paid_reason','hidro_nf_delete_reason','hidro_nf_audit_insert','hidro_nf_audit_update','hidro_nf_audit_delete'):
        execute(f'DROP TRIGGER {name}')
    execute('DROP TRIGGER hidro_nf_requires_bm')
    execute(f'''CREATE TRIGGER hidro_nf_requires_bm BEFORE INSERT ON {N} BEGIN
      SELECT CASE WHEN NEW.valor_pago<0 OR NEW.valor_pago!=round(NEW.valor_pago,2) THEN RAISE(ABORT,'Valor fiscal exige centavos exatos e não negativos.') END;
      SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM gestao_contratos_bm b LEFT JOIN gestao_contratos_evento e ON e.id=b.evento_id LEFT JOIN gestao_contratos_os o ON o.id=b.os_id WHERE b.id=NEW.bm_id AND coalesce(b.evento_id,0)=coalesce(NEW.evento_id,0) AND coalesce(b.os_id,0)=coalesce(NEW.os_id,0) AND ((b.evento_id IS NOT NULL AND b.os_id IS NULL AND e.contrato_terceiro_id=NEW.contrato_id) OR(b.os_id IS NOT NULL AND b.evento_id IS NULL AND b.contrato_id=NEW.contrato_id AND o.contrato_id=NEW.contrato_id))) THEN RAISE(ABORT,'Nova NF exige BM da mesma origem financeira.') END;
      END''')
    history=f'EXISTS(SELECT 1 FROM {P} WHERE nf_id=OLD.id)'
    snapshot=lambda side:f"json_set({old.snapshot(side)},'$.vencimento_original',{side}.vencimento_original,'$.cancelada_em',{side}.cancelada_em,'$.cancelada_por_id',{side}.cancelada_por_id,'$.motivo_cancelamento',{side}.motivo_cancelamento)"
    final_snapshot=f"json_set({snapshot('NEW')},'$.financeiro_autorizou',CASE WHEN OLD.financeiro_autorizou IS NOT NEW.financeiro_autorizou THEN NEW.financeiro_autorizou WHEN {NET('NEW.id')}>0 AND {NET('NEW.id')}={CENT('NEW.valor_pago')} THEN 1 ELSE 0 END)"
    execute(f'''CREATE TRIGGER hidro_nf_paid_reason BEFORE UPDATE ON {N} BEGIN
      SELECT CASE WHEN NEW.valor_pago<0 OR NEW.valor_pago!=round(NEW.valor_pago,2) THEN RAISE(ABORT,'Valor fiscal exige centavos exatos e não negativos.') END;
      SELECT CASE WHEN {MODE('projection')}=1 AND ({content_changed}) THEN RAISE(ABORT,'Projeção só altera a situação derivada.') END;
      SELECT CASE WHEN {MODE('projection')}=0 AND ({changed}) AND (OLD.financeiro_autorizou=1 OR {history}) AND {CTX('autor_grupo')}='financeiro' THEN RAISE(ABORT,'NF com pagamento é somente leitura para Financeiro.') END;
      SELECT CASE WHEN {MODE('projection')}=0 AND ({changed}) AND (OLD.financeiro_autorizou=1 OR {history}) AND {CTX('autor_grupo')} IS NOT 'suprimento' THEN RAISE(ABORT,'Correção de NF com movimentos exige Suprimento.') END;
      SELECT CASE WHEN {MODE('projection')}=0 AND ({changed}) AND (OLD.financeiro_autorizou=1 OR {history}) AND coalesce({CTX('justificativa')},'')='' THEN RAISE(ABORT,'Justificativa obrigatória na correção financeira.') END;
      SELECT CASE WHEN OLD.vencimento_original IS NOT NULL AND OLD.vencimento_original IS NOT NEW.vencimento_original THEN RAISE(ABORT,'Vencimento original é permanente; registre acordo.') END;
      SELECT CASE WHEN ({history} OR EXISTS(SELECT 1 FROM {S} WHERE nf_id=OLD.id) OR EXISTS(SELECT 1 FROM {A} WHERE nf_id=OLD.id)) AND (OLD.contrato_id IS NOT NEW.contrato_id OR OLD.evento_id IS NOT NEW.evento_id OR OLD.os_id IS NOT NEW.os_id OR OLD.bm_id IS NOT NEW.bm_id) THEN RAISE(ABORT,'Origem de movimentos/acordos é permanente; cancele e registre a obrigação no contexto correto.') END;
      SELECT CASE WHEN {CENT('NEW.valor_pago')}<{NET('OLD.id')} AND NOT(OLD.financeiro_autorizou=1 AND NEW.financeiro_autorizou=0 AND {CTX('autor_grupo')}='suprimento') THEN RAISE(ABORT,'Valor fiscal inferior ao pago líquido; estorne antes de corrigir.') END;
      SELECT CASE WHEN (OLD.cancelada_em IS NOT NEW.cancelada_em OR OLD.cancelada_por_id IS NOT NEW.cancelada_por_id OR OLD.motivo_cancelamento IS NOT NEW.motivo_cancelamento) AND ({CTX('autor_grupo')} IS NOT 'suprimento' OR coalesce({CTX('justificativa')},'')='' OR OLD.cancelada_em IS NOT NULL OR NEW.cancelada_em IS NULL OR {NET('OLD.id')}!=0) THEN RAISE(ABORT,'Cancelamento exige Suprimento, justificativa e reversões completas.') END;
      END''')
    execute(f'''CREATE TRIGGER hidro_nf_delete_reason BEFORE DELETE ON {N} BEGIN
      SELECT CASE WHEN {history} OR EXISTS(SELECT 1 FROM {S} WHERE nf_id=OLD.id) OR EXISTS(SELECT 1 FROM {A} WHERE nf_id=OLD.id) THEN RAISE(ABORT,'Histórico financeiro protegido: utilize cancelamento lógico.') END;
      SELECT CASE WHEN OLD.financeiro_autorizou=1 AND (coalesce({CTX('justificativa')},'')='' OR {CTX('autor_grupo')}='financeiro') THEN RAISE(ABORT,'Exclusão financeira não autorizada.') END; END''')
    # Mantém os nomes originais e a fonte única de eventos NF; projeções não inventam pagamentos.
    for action,side,before,after,operation,condition in (
        ('INSERT','NEW','NULL',snapshot('NEW'),"'criacao'",''),
        ('UPDATE','NEW',snapshot('OLD'),final_snapshot,"CASE WHEN NEW.cancelada_em IS NOT OLD.cancelada_em THEN 'cancelamento' WHEN EXISTS(SELECT 1 FROM "+P+" WHERE nf_id=NEW.id) THEN 'correcao_paga' ELSE 'alteracao' END",f"WHEN {MODE('projection')}=0 AND ({content_changed})"),
        ('DELETE','OLD',snapshot('OLD'),'NULL',"'exclusao'",'')):
        execute(f'''CREATE TRIGGER hidro_nf_audit_{action.lower()} AFTER {action} ON {N} {condition} BEGIN
          INSERT INTO {R}(content_type_id,object_id,acao,usuario_id,modelo,representacao_objeto,detalhes,data_hora,operacao_financeira,estado_anterior,estado_posterior,justificativa,autor_nome,autor_grupo)
          VALUES((SELECT id FROM django_content_type WHERE app_label='gestao_contratos' AND model='nf'),{side}.id,'{'criado' if action=='INSERT' else 'atualizado'}',{CTX('usuario_id')},'NF','NF #'||{side}.id,'Operação de NF; trilha de liquidação nos movimentos.',strftime('%Y-%m-%d %H:%M:%f','now'),{operation},{before},{after},{CTX('justificativa')},{CTX('autor_nome')},{CTX('autor_grupo')}); END''')
    # Conversão de chamadas antigas: o booleano não vira uma segunda fonte monetária.
    def compatibility_payment(condition):
        return f'''INSERT INTO {P}(nf_id,valor,data_pagamento,tipo,justificativa,observacao,comprovante,chave_idempotencia,payload_hash,origem_registro,registrado_em,registrado_por_id)
        SELECT NEW.id,NEW.valor_pago,NEW.data_pagamento,'pagamento',coalesce({CTX('justificativa')},''),coalesce(NEW.observacao,''),NEW.comprovante_pagamento,lower(hex(randomblob(24))),'',CASE WHEN {MODE('legacy')}=1 THEN 'legado_nf_integral' ELSE 'normal' END,strftime('%Y-%m-%d %H:%M:%f','now'),{CTX('usuario_id')} WHERE {condition};'''
    reversible=f"(p.centavos-coalesce((SELECT sum(e.centavos) FROM {P} e WHERE e.referencia_estorno_id=p.id),0))"
    execute(f'''CREATE TRIGGER hidro_nf_compat_insert AFTER INSERT ON {N} BEGIN {compatibility_payment('NEW.financeiro_autorizou=1')} END''')
    execute(f'''CREATE TRIGGER hidro_nf_compat_update AFTER UPDATE ON {N} WHEN {MODE('projection')}=0 AND ({changed}) BEGIN
      {compatibility_payment('OLD.financeiro_autorizou=0 AND NEW.financeiro_autorizou=1')}
      INSERT INTO {P}(nf_id,valor,data_pagamento,tipo,referencia_estorno_id,programacao_id,justificativa,observacao,chave_idempotencia,payload_hash,origem_registro,registrado_em,registrado_por_id)
      SELECT NEW.id,printf('%d.%02d',{reversible}/100,{reversible}%100),date('now'),'estorno',p.id,p.programacao_id,coalesce({CTX('justificativa')},''),'Reversão da liquidação integral pelo adaptador legado.',lower(hex(randomblob(24))),'','normal',strftime('%Y-%m-%d %H:%M:%f','now'),{CTX('usuario_id')} FROM {P} p WHERE p.nf_id=NEW.id AND p.tipo='pagamento' AND OLD.financeiro_autorizou=1 AND NEW.financeiro_autorizou=0 AND p.centavos>coalesce((SELECT sum(e.centavos) FROM {P} e WHERE e.referencia_estorno_id=p.id),0);
      SELECT hidro_project_invoice(NEW.id); END''')
    valid_origin=f'''EXISTS(SELECT 1 FROM {N} n JOIN gestao_contratos_bm b ON b.id=n.bm_id LEFT JOIN gestao_contratos_evento e ON e.id=n.evento_id LEFT JOIN gestao_contratos_os o ON o.id=n.os_id
      WHERE n.id=NEW.nf_id AND n.cancelada_em IS NULL AND b.aprovacao_pagamento='aprovado' AND (b.status_coordenador='aprovado' OR b.status_gerente='aprovado') AND b.status_coordenador!='reprovado' AND b.status_gerente!='reprovado'
      AND coalesce(b.evento_id,0)=coalesce(n.evento_id,0) AND coalesce(b.os_id,0)=coalesce(n.os_id,0)
      AND ((n.evento_id IS NOT NULL AND n.os_id IS NULL AND e.contrato_terceiro_id=n.contrato_id) OR(n.os_id IS NOT NULL AND n.evento_id IS NULL AND o.contrato_id=n.contrato_id AND b.contrato_id=n.contrato_id AND o.status!='cancelada')))'''
    execute(f'''CREATE TRIGGER hidro_pagamento_validate BEFORE INSERT ON {P} BEGIN
      SELECT CASE WHEN NEW.valor!=round(NEW.valor,2) OR NEW.valor<=0 THEN RAISE(ABORT,'Movimento exige valor positivo em centavos.') END;
      SELECT CASE WHEN NEW.origem_registro='legado_nf_integral' AND ({MODE('legacy')}!=1 OR NEW.tipo!='pagamento' OR NOT EXISTS(SELECT 1 FROM {N} WHERE id=NEW.nf_id AND financeiro_autorizou=1 AND {CENT('valor_pago')}={CENT('NEW.valor')})) THEN RAISE(ABORT,'Abertura legada restrita à migração conciliada.') END;
      SELECT CASE WHEN NEW.origem_registro!='legado_nf_integral' AND ({CTX('autor_grupo')} IS NULL OR {CTX('autor_grupo')} NOT IN ('financeiro','suprimento') OR NEW.registrado_por_id IS NOT {CTX('usuario_id')} OR NEW.data_pagamento IS NULL) THEN RAISE(ABORT,'Movimento não autorizado.') END;
      SELECT CASE WHEN NEW.tipo='pagamento' AND NEW.origem_registro!='legado_nf_integral' AND NOT({valid_origin}) THEN RAISE(ABORT,'Nova liquidação exige NF/origem válidas e aprovações operacional/Diretoria.') END;
      SELECT CASE WHEN NEW.tipo='pagamento' AND {CENT('NEW.valor')}>{CENT('(SELECT valor_pago FROM '+N+' WHERE id=NEW.nf_id)')}-{NET('NEW.nf_id')} THEN RAISE(ABORT,'Pagamento superior ao saldo fiscal.') END;
      SELECT CASE WHEN NEW.tipo='pagamento' AND NEW.referencia_estorno_id IS NOT NULL THEN RAISE(ABORT,'Pagamento não referencia estorno.') END;
      SELECT CASE WHEN NEW.tipo='estorno' AND ({CTX('autor_grupo')} IS NOT 'suprimento' OR trim(NEW.justificativa)='' OR NOT EXISTS(SELECT 1 FROM {P} p WHERE p.id=NEW.referencia_estorno_id AND p.tipo='pagamento' AND p.nf_id=NEW.nf_id AND p.programacao_id IS NEW.programacao_id AND {CENT('NEW.valor')}<=p.centavos-coalesce((SELECT sum(e.centavos) FROM {P} e WHERE e.referencia_estorno_id=p.id),0))) THEN RAISE(ABORT,'Estorno exige referência válida, saldo reversível e justificativa do Suprimento.') END;
      SELECT CASE WHEN NEW.programacao_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM {S} WHERE id=NEW.programacao_id AND nf_id=NEW.nf_id) THEN RAISE(ABORT,'Programação de outra NF.') END;
      SELECT CASE WHEN NEW.tipo NOT IN ('pagamento','estorno') THEN RAISE(ABORT,'Tipo de movimento inválido.') END;
      SELECT CASE WHEN NEW.origem_registro NOT IN ('normal','legado_nf_integral') THEN RAISE(ABORT,'Origem de movimento inválida.') END;
      SELECT CASE WHEN NEW.tipo='pagamento' AND NEW.programacao_id IS NOT NULL AND EXISTS(SELECT 1 FROM {S} s WHERE s.id=NEW.programacao_id AND (s.cancelada=1 OR EXISTS(SELECT 1 FROM {S} x WHERE x.substitui_id=s.id))) THEN RAISE(ABORT,'Vínculo com programação cancelada ou substituída.') END;
      END''')
    for table,label in ((P,'pagamento'),(S,'programacao'),(A,'reprogramacao')):
        for action in ('UPDATE','DELETE'):
            execute(f"CREATE TRIGGER hidro_{label}_no_{action.lower()} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT,'Registro financeiro imutável; acrescente reversão ou revisão.'); END")
    execute(f'''CREATE TRIGGER hidro_pagamento_project AFTER INSERT ON {P} BEGIN SELECT hidro_project_invoice(NEW.nf_id); END''')
    pay_snapshot=root_snapshot('NEW.nf_id',(('movimento_id','NEW.id'),('tipo_movimento','NEW.tipo'),('valor_movimento','NEW.valor'),('data_efetiva','NEW.data_pagamento'),('referencia_estorno_id','NEW.referencia_estorno_id'),('comprovante_pagamento','NEW.comprovante'),('origem_registro','NEW.origem_registro')))
    prior=f"({NET('NEW.nf_id')}-CASE NEW.tipo WHEN 'estorno' THEN -NEW.centavos ELSE NEW.centavos END)"
    pay_before=f"json_set({root_snapshot('NEW.nf_id')},'$.liquidado_centavos',{prior},'$.financeiro_autorizou',CASE WHEN {prior}>0 AND {prior}={CENT('(SELECT valor_pago FROM '+N+' WHERE id=NEW.nf_id)')} THEN 1 ELSE 0 END)"
    execute(audit_insert(P,'pagamento',"CASE NEW.tipo WHEN 'estorno' THEN 'estorno' ELSE 'liquidacao' END",pay_snapshot,"WHEN NEW.origem_registro!='legado_nf_integral'",pay_before))
    for table,label in ((S,'programacao'),(A,'reprogramacao')):
        execute(f'''CREATE TRIGGER hidro_{label}_validate BEFORE INSERT ON {table} BEGIN
          SELECT CASE WHEN {CTX('autor_grupo')} IS NULL OR {CTX('autor_grupo')} NOT IN ('financeiro','suprimento') OR NEW.registrado_por_id IS NOT {CTX('usuario_id')} OR NOT EXISTS(SELECT 1 FROM {N} WHERE id=NEW.nf_id AND cancelada_em IS NULL) THEN RAISE(ABORT,'Programação/acordo não autorizado.') END;
          SELECT CASE WHEN {NET('NEW.nf_id')}>={CENT('(SELECT valor_pago FROM '+N+' WHERE id=NEW.nf_id)')} THEN RAISE(ABORT,'NF sem saldo pendente.') END;
          END''')
    execute(f'''CREATE TRIGGER hidro_programacao_chain BEFORE INSERT ON {S} BEGIN
      SELECT CASE WHEN trim(NEW.justificativa)='' OR NEW.valor_previsto!=round(NEW.valor_previsto,2) THEN RAISE(ABORT,'Programação/revisão exige justificativa e centavos exatos.') END;
      SELECT CASE WHEN NEW.substitui_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM {S} s WHERE s.id=NEW.substitui_id AND s.nf_id=NEW.nf_id AND s.grupo=NEW.grupo AND NOT EXISTS(SELECT 1 FROM {S} x WHERE x.substitui_id=s.id)) THEN RAISE(ABORT,'Revisão exige predecessora atual da mesma NF/grupo.') END;
      SELECT CASE WHEN NEW.substitui_id IS NULL AND EXISTS(SELECT 1 FROM {S} WHERE grupo=NEW.grupo) THEN RAISE(ABORT,'Grupo de programação já existente.') END;
      SELECT CASE WHEN NEW.cancelada=1 AND NEW.substitui_id IS NULL THEN RAISE(ABORT,'Cancelamento exige parcela predecessora.') END;
      SELECT CASE WHEN NEW.substitui_id IS NOT NULL AND NEW.centavos<coalesce((SELECT sum(CASE p.tipo WHEN 'estorno' THEN -p.centavos ELSE p.centavos END) FROM {P} p JOIN {S} s ON s.id=p.programacao_id WHERE p.nf_id=NEW.nf_id AND s.grupo=NEW.grupo),0) THEN RAISE(ABORT,'Programação inferior ao já liquidado por vínculo explícito.') END;
      SELECT CASE WHEN NEW.acordo_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM {A} WHERE id=NEW.acordo_id AND nf_id=NEW.nf_id) THEN RAISE(ABORT,'Acordo de outra NF.') END;
      END''')
    group_paid=lambda alias:f"coalesce((SELECT sum(CASE p.tipo WHEN 'estorno' THEN -p.centavos ELSE p.centavos END) FROM {P} p JOIN {S} g ON g.id=p.programacao_id WHERE p.nf_id=NEW.nf_id AND g.grupo={alias}.grupo),0)"
    existing=f"coalesce((SELECT sum(max(s.centavos-{group_paid('s')},0)) FROM {S} s WHERE s.nf_id=NEW.nf_id AND s.id IS NOT NEW.substitui_id AND s.cancelada=0 AND NOT EXISTS(SELECT 1 FROM {S} x WHERE x.substitui_id=s.id)),0)"
    new_remaining=f"CASE WHEN NEW.cancelada=1 THEN 0 ELSE max({CENT('NEW.valor_previsto')}-{group_paid('NEW')},0) END"
    previous_remaining=f"max(coalesce((SELECT centavos FROM {S} WHERE id=NEW.substitui_id),0)-{group_paid('NEW')},0)"
    execute(f'''CREATE TRIGGER hidro_programacao_cap BEFORE INSERT ON {S} WHEN {existing}+({new_remaining})>{CENT('(SELECT valor_pago FROM '+N+' WHERE id=NEW.nf_id)')}-{NET('NEW.nf_id')} AND (NEW.substitui_id IS NULL OR ({new_remaining})>{previous_remaining}) BEGIN SELECT RAISE(ABORT,'Programação acima do saldo disponível; não há alocação automática de pagamentos.'); END''')
    execute(f'''CREATE TRIGGER hidro_reprogramacao_scope BEFORE INSERT ON {A} BEGIN
      SELECT CASE WHEN trim(NEW.motivo)='' OR NEW.novo_vencimento IS NULL THEN RAISE(ABORT,'Acordo exige novo prazo e motivo.') END;
      SELECT CASE WHEN NEW.programacao_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM {S} s WHERE s.id=NEW.programacao_id AND s.nf_id=NEW.nf_id AND NOT EXISTS(SELECT 1 FROM {S} x WHERE x.substitui_id=s.id)) THEN RAISE(ABORT,'Acordo exige programação atual da mesma NF.') END;
      SELECT CASE WHEN NEW.vencimento_anterior IS NOT (CASE WHEN NEW.programacao_id IS NOT NULL THEN (SELECT data_prevista FROM {S} WHERE id=NEW.programacao_id) ELSE coalesce((SELECT novo_vencimento FROM {A} WHERE nf_id=NEW.nf_id AND programacao_id IS NULL ORDER BY id DESC LIMIT 1),(SELECT vencimento_original FROM {N} WHERE id=NEW.nf_id)) END) THEN RAISE(ABORT,'Prazo anterior divergente do último acordo/programação.') END;
      END''')
    program_before=f"CASE WHEN NEW.substitui_id IS NULL THEN NULL ELSE {root_snapshot('NEW.nf_id',(('programacao_id','NEW.substitui_id'),('valor_previsto',f'(SELECT valor_previsto FROM {S} WHERE id=NEW.substitui_id)'),('data_prevista',f'(SELECT data_prevista FROM {S} WHERE id=NEW.substitui_id)'),('cancelada',f'(SELECT cancelada FROM {S} WHERE id=NEW.substitui_id)')))} END"
    execute(audit_insert(S,'programacao',"'programacao'",root_snapshot('NEW.nf_id',(('programacao_id','NEW.id'),('programacao_anterior_id','NEW.substitui_id'),('valor_previsto','NEW.valor_previsto'),('data_prevista','NEW.data_prevista'),('cancelada','NEW.cancelada'),('acordo_id','NEW.acordo_id'))),before=program_before))
    execute(audit_insert(A,'reprogramacao',"'reprogramacao'",root_snapshot('NEW.nf_id',(('acordo_id','NEW.id'),('vencimento_anterior','NEW.vencimento_anterior'),('novo_vencimento','NEW.novo_vencimento'),('vencimento_atual','NEW.novo_vencimento'),('motivo','NEW.motivo'),('responsavel_acordo','NEW.responsavel_acordo'),('documento_acordo','NEW.documento'))),before=root_snapshot('NEW.nf_id',(('vencimento_atual','NEW.vencimento_anterior'),))))
    # SQLite executa AFTER triggers em ordem inversa de criação: primeiro
    # projeta a situação derivada; no cadastro NF registra criação antes da liquidação.
    for name in ('hidro_nf_audit_insert','hidro_nf_audit_update','hidro_pagamento_project'):
        with editor.connection.cursor() as cursor:ddl=cursor.execute("SELECT sql FROM sqlite_master WHERE name=%s",[name]).fetchone()[0]
        execute(f'DROP TRIGGER {name}');execute(ddl)


def remove(apps,editor):
    # Recusa apagar história criada após ativação.
    for table in (S,A):
        if editor.connection.cursor().execute(f'SELECT count(*) FROM {table}').fetchone()[0]:raise RuntimeError('Há programação/acordos reais: reversão destrutiva não autorizada.')
    if editor.connection.cursor().execute(f"SELECT count(*) FROM {P} WHERE origem_registro!='legado_nf_integral'").fetchone()[0]:raise RuntimeError('Há movimentos novos: preserve o ledger, não reverta schema.')
    with editor.connection.cursor() as cursor:
        names=[r[0] for r in cursor.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND (name LIKE 'hidro_pagamento_%' OR name LIKE 'hidro_programacao_%' OR name LIKE 'hidro_reprogramacao_%' OR name LIKE 'hidro_nf_compat_%')")]
    for name in names:editor.execute(f'DROP TRIGGER {name}')
    old=import_module('gestao_contratos.migrations.0118_trilha_nf_transacional')
    old.remove(apps,editor);old.create(apps,editor)


class Migration(migrations.Migration):
    dependencies=[('gestao_contratos','0121_abertura_legada_nf')]
    operations=[migrations.RunPython(create,remove)]
