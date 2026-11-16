"""Defesas transacionais dos ciclos e renovação obrigatória na liquidação."""
import json
from datetime import date, timedelta

from . import bm_cycles as c

TABLES = ('gestao_contratos_ciclopagamentobm',
          'gestao_contratos_decisaociclobm', 'gestao_contratos_pagamentociclobm')
TRIGGERS = {f'hidro_ciclo_{kind}_{action}' for kind in ('programacao', 'decisao', 'vinculo')
            for action in ('validate', 'no_update', 'no_delete', 'audit')} | {
    'hidro_ciclo_payment_guard', 'hidro_ciclo_payment_link', 'hidro_ciclo_calendario_preservado'}


def validate_record(db, kind, encoded):
    value = json.loads(encoded)
    mode = c._operation.get()
    actor = c.row(db, 'SELECT * FROM gestao_contratos_user WHERE id=?', (mode.get('actor'),)) if mode.get('actor') else None
    if actor and not actor['is_active']:
        return 'Usuário inativo.'
    if kind == 'vinculo':
        if mode.get('operation') != 'vincular_pagamento' or mode.get('payment_id') != value['pagamento_id']:
            return 'O vínculo é registrado somente pelo gatilho do pagamento.'
        payment = c.row(db, '''SELECT p.*,n.bm_id FROM gestao_contratos_pagamentonf p
            JOIN gestao_contratos_nf n ON n.id=p.nf_id WHERE p.id=?''', (value['pagamento_id'],))
        current = c.head(db, payment['bm_id']) if payment else None
        return '' if payment and payment['tipo'] == 'pagamento' and current and current['id'] == value['ciclo_id'] else 'Pagamento/ciclo incompatível.'
    if value.get('registrado_por_id') != mode.get('actor'):
        return 'Autoria incompatível com o contexto da operação.'
    if kind == 'programacao':
        if mode.get('operation') not in {'processar', 'revisar'} or value['bm_id'] != mode.get('bm_id'):
            return 'Ciclo exige processamento transacional autorizado.'
        if mode['operation'] == 'revisar' and (not actor or actor['grupo'] != 'suprimento'):
            return 'Revisão expressa exige Suprimento.'
        if mode['operation'] == 'processar' and actor and actor['grupo'] not in {'financeiro', 'suprimento'}:
            return 'Perfil sem competência para programação.'
        today = date.fromisoformat(mode['today']) if mode.get('today') else c.timezone.localdate()
        if today > c.timezone.localdate():
            return 'Não encerre ciclo futuro.'
        state = c.financial_state(db, value['bm_id'], today)
        if state['errors'] or state['balance_cents'] <= 0 or not state['reference']:
            return 'BM sem saldo, sem data confiável ou com impedimento.'
        if c.cents(value['saldo_inclusao']) != state['balance_cents'] or value['versao_material'] != state['version']:
            return 'Snapshot não corresponde ao saldo/contexto atual.'
        if json.loads(value['contexto_inclusao']) != c.snapshot(state):
            return 'Contexto de inclusão divergente.'
        previous = c.head(db, value['bm_id'])
        if previous is None:
            if value['tipo'] != 'inicial' or value['numero'] != 1 or value['anterior_id'] is not None or value['data_prevista'] != state['reference'].isoformat():
                return 'Programação inicial inválida.'
        else:
            if value['anterior_id'] != previous['id'] or value['numero'] != previous['numero'] + 1:
                return 'Ciclo anterior já substituído ou sequência inválida.'
            if value['tipo'] == 'revisao':
                scheduled=c.programmed_date(state,previous)
                calendar=c.row(db,'SELECT id FROM gestao_contratos_calendariopagamento WHERE data_pagamento=?',(scheduled.isoformat(),))
                calendar_id=previous['calendario_id'] if previous['data_prevista']==scheduled.isoformat() else calendar['id'] if calendar else None
                if mode['operation'] != 'revisar' or not str(value['motivo']).strip() or value['data_prevista'] != scheduled.isoformat() or value['calendario_id'] != calendar_id:
                    return 'Revisão exige justificativa e preservação da data programada.'
            elif value['tipo'] == 'reprogramacao':
                previous_date=c.programmed_date(state,previous)
                if previous_date >= today:
                    return 'A programação anterior ainda não encerrou.'
                if not c.operational(state['bm']) or state['bm']['aprovacao_pagamento'] not in {'pendente','aprovado'}:
                    return 'Primeiras aprovações ainda não concluídas.'
                if db.execute("SELECT 1 FROM gestao_contratos_decisaociclobm WHERE ciclo_id=? AND situacao='reprovado'", (previous['id'],)).fetchone():
                    return 'Reprovação exige revisão expressa; não pode ser apagada pela troca de data.'
                floor = max(today, previous_date + timedelta(days=1), state['not_before'] or state['reference'])
                calendar = c.row(db, 'SELECT * FROM gestao_contratos_calendariopagamento WHERE data_pagamento>=? ORDER BY data_pagamento LIMIT 1', (floor.isoformat(),))
                if not calendar or value['calendario_id'] != calendar['id'] or value['data_prevista'] != calendar['data_pagamento']:
                    return 'Próxima data deve vir do calendário de pagamentos vigente.'
            else:
                return 'Tipo de sucessão inválido.'
        if value['calendario_id'] is not None:
            calendar = c.row(db, 'SELECT * FROM gestao_contratos_calendariopagamento WHERE id=?', (value['calendario_id'],))
            if not calendar or calendar['data_pagamento'] != value['data_prevista']:
                return 'Calendário e data incompatíveis.'
        return ''
    if kind == 'decisao':
        if mode.get('operation') != 'decidir' or not actor:
            return 'Decisão exige usuário autenticado e fluxo próprio.'
        cycle = c.row(db, 'SELECT * FROM gestao_contratos_ciclopagamentobm WHERE id=?', (value['ciclo_id'],))
        if not cycle or cycle['bm_id'] != mode.get('bm_id') or cycle['tipo'] == 'inicial':
            return 'A primeira aprovação continua no fluxo original.'
        state = c.cycle_state(db, cycle['bm_id'])
        if state['cycle']['id'] != cycle['id'] or state['errors'] or state['balance_cents'] <= 0:
            return 'Ciclo superado, sem saldo ou com impedimento.'
        if not c.operational(state['bm']) or state['bm']['aprovacao_pagamento'] not in {'pendente','aprovado'}:
            return 'BM exige conclusão das aprovações iniciais.'
        manager = state['manager']
        if not manager or value['responsavel_id'] != manager['id']:
            return 'Líder de Contrato responsável ausente ou superado.'
        if value['versao_material'] != state['version'] or c.cents(value['saldo_avaliado']) != state['balance_cents']:
            return 'Valor/contexto alterado após a conferência.'
        if value['etapa'] == 'gerencia':
            if state['stage'] != 'gerencia' or actor['grupo'] not in c.RESPONSIBLE_ROLES or manager['id'] != actor['id']:
                return 'Somente o gerente vinculado decide a etapa gerencial pendente.'
        elif value['etapa'] == 'diretoria':
            if state['stage'] != 'diretoria' or actor['grupo'] != 'diretoria':
                return 'Diretoria decide somente após aprovação gerencial válida neste ciclo.'
        else:
            return 'Etapa inválida.'
        if value['situacao'] not in {'aprovado', 'reprovado'} or (value['situacao'] == 'reprovado' and not str(value['justificativa']).strip()) or len(value['justificativa']) > 4000:
            return 'Decisão inválida ou justificativa obrigatória ausente.'
        return ''
    return 'Tipo de registro desconhecido.'


def link_payment(conn, payment_id):
    db = conn.connection
    payment = c.row(db, '''SELECT p.*,n.bm_id FROM gestao_contratos_pagamentonf p
        JOIN gestao_contratos_nf n ON n.id=p.nf_id WHERE p.id=?''', (payment_id,))
    current = c.head(db, payment['bm_id']) if payment else None
    if not current or payment['tipo'] != 'pagamento':
        return 0
    token = c._operation.set(dict(operation='vincular_pagamento', payment_id=payment_id))
    try:
        db.execute('INSERT INTO gestao_contratos_pagamentociclobm(pagamento_id,ciclo_id) VALUES(?,?)', (payment_id, current['id']))
    finally:
        c._operation.reset(token)
    return 1


def install(apps, editor):
    if editor.connection.vendor != 'sqlite':
        raise RuntimeError('Homologue os gatilhos equivalentes antes de utilizar outro banco.')
    fields = {
        'programacao': ('bm_id','numero','anterior_id','tipo','data_prevista','calendario_id','saldo_inclusao','motivo','contexto_inclusao','versao_material','registrado_por_id','registrado_em'),
        'decisao': ('ciclo_id','etapa','situacao','responsavel_id','saldo_avaliado','versao_material','justificativa','registrado_por_id','registrado_em'),
        'vinculo': ('pagamento_id','ciclo_id'),
    }
    for (kind, names), table in zip(fields.items(), TABLES):
        encoded = 'json_object(' + ','.join(f"'{field}',NEW.{field}" for field in names) + ')'
        editor.execute(f'''CREATE TRIGGER hidro_ciclo_{kind}_validate BEFORE INSERT ON {table}
            WHEN hidro_validar_ciclo_bm('{kind}',{encoded})!=''
            BEGIN SELECT RAISE(ABORT,'Ciclo de BM inválido: confira competência, contexto, saldo, calendário e aprovações.'); END''')
        for action in ('UPDATE', 'DELETE'):
            editor.execute(f'''CREATE TRIGGER hidro_ciclo_{kind}_no_{action.lower()} BEFORE {action} ON {table}
                BEGIN SELECT RAISE(ABORT,'Histórico de ciclos/decisões de BM é imutável.'); END''')
        object_id = 'NEW.bm_id' if kind == 'programacao' else '(SELECT bm_id FROM gestao_contratos_ciclopagamentobm WHERE id=NEW.ciclo_id)'
        content_model = 'bm'
        editor.execute(f'''CREATE TRIGGER hidro_ciclo_{kind}_audit AFTER INSERT ON {table}
            BEGIN INSERT INTO gestao_contratos_registroauditoria(
                content_type_id,object_id,acao,usuario_id,modelo,representacao_objeto,detalhes,data_hora,
                operacao_financeira,estado_anterior,estado_posterior,autor_nome,autor_grupo)
            VALUES((SELECT id FROM django_content_type WHERE app_label='gestao_contratos' AND model='{content_model}'),
                {object_id},'criado',json_extract(hidro_financial_context(),'$.usuario_id'),'{content_model}',
                'Ciclo de pagamento de BM','Registro permanente de {kind}',strftime('%Y-%m-%d %H:%M:%f','now'),
                'ciclo_bm_{kind}',NULL,{encoded},json_extract(hidro_financial_context(),'$.autor_nome'),json_extract(hidro_financial_context(),'$.autor_grupo'));
            END''')
    editor.execute('''CREATE TRIGGER hidro_ciclo_payment_guard BEFORE INSERT ON gestao_contratos_pagamentonf
        WHEN NEW.tipo='pagamento' AND hidro_ciclo_erro_pagamento(NEW.nf_id,NEW.centavos)!=''
        BEGIN SELECT RAISE(ABORT,'O ciclo atual exige nova aprovação gerencial e autorização da Diretoria sobre o saldo.'); END''')
    editor.execute('''CREATE TRIGGER hidro_ciclo_payment_link AFTER INSERT ON gestao_contratos_pagamentonf
        WHEN NEW.tipo='pagamento' BEGIN SELECT hidro_vincular_pagamento_ciclo(NEW.id); END''')
    editor.execute('''CREATE TRIGGER hidro_ciclo_calendario_preservado BEFORE UPDATE OF data_pagamento ON gestao_contratos_calendariopagamento
        WHEN OLD.data_pagamento IS NOT NEW.data_pagamento AND EXISTS(SELECT 1 FROM gestao_contratos_ciclopagamentobm WHERE calendario_id=OLD.id)
        BEGIN SELECT RAISE(ABORT,'Calendário já utilizado por ciclos: acrescente nova data, sem reescrever o histórico.'); END''')
    editor.connection._bm_cycles_enabled = True


def uninstall(apps, editor):
    for table in TABLES:
        if editor.connection.cursor().execute(f'SELECT 1 FROM {table} LIMIT 1').fetchone():
            raise RuntimeError('Há ciclos, decisões ou vínculos registrados; reversão destrutiva recusada. Faça correção progressiva.')
    for name in TRIGGERS:
        editor.execute(f'DROP TRIGGER {name}')
    editor.connection._bm_cycles_enabled = False
