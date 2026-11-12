"""Contextos internos de migração/projeção, nunca obtidos de POST."""
from contextvars import ContextVar
from contextlib import contextmanager
import json
from decimal import Decimal

_mode=ContextVar('hidro_ledger_mode',default={})

LEDGER_TRIGGERS={'hidro_nf_compat_insert','hidro_nf_compat_update','hidro_pagamento_project',
    'hidro_programacao_chain','hidro_programacao_cap','hidro_reprogramacao_scope'}|{
    f'hidro_{entity}_{action}' for entity in ('pagamento','programacao','reprogramacao')
    for action in ('validate','no_update','no_delete','audit_insert')}


@contextmanager
def ledger_context(**flags):
    token=_mode.set({**_mode.get(),**flags})
    try:yield
    finally:_mode.reset(token)


def mode_json():return json.dumps(_mode.get())


def project_invoice(connection,nf_id):
    """Executada pelo trigger na conexão corrente; só projeta o ledger exato."""
    raw=connection.connection
    if not raw.execute("SELECT 1 FROM django_migrations WHERE app='gestao_contratos' AND name='0122_ledger_transacional'").fetchone():
        return 0
    nf=raw.execute('SELECT valor_pago,evento_id,os_id,financeiro_autorizou FROM gestao_contratos_nf WHERE id=?',(nf_id,)).fetchone()
    if not nf:return 0
    paid=raw.execute("SELECT coalesce(sum(CASE tipo WHEN 'estorno' THEN -centavos ELSE centavos END),0) FROM gestao_contratos_pagamentonf WHERE nf_id=?",(nf_id,)).fetchone()[0]
    full=bool(paid>0 and Decimal(str(nf[0]))*100==paid)
    with ledger_context(projection=True):
        if bool(nf[3])!=full:raw.execute('UPDATE gestao_contratos_nf SET financeiro_autorizou=? WHERE id=?',(full,nf_id))
        if not _mode.get().get('legacy'):
            field,table,origin_id=('evento_id','gestao_contratos_evento',nf[1]) if nf[1] else ('os_id','gestao_contratos_os',nf[2])
            if origin_id:
                total=raw.execute(f"SELECT coalesce(sum(CASE p.tipo WHEN 'estorno' THEN -p.centavos ELSE p.centavos END),0) FROM gestao_contratos_pagamentonf p JOIN gestao_contratos_nf n ON n.id=p.nf_id WHERE n.{field}=?",(origin_id,)).fetchone()[0]
                last=raw.execute(f"SELECT max(p.data_pagamento) FROM gestao_contratos_pagamentonf p JOIN gestao_contratos_nf n ON n.id=p.nf_id WHERE n.{field}=? AND p.tipo='pagamento' AND p.centavos>coalesce((SELECT sum(e.centavos) FROM gestao_contratos_pagamentonf e WHERE e.referencia_estorno_id=p.id),0)",(origin_id,)).fetchone()[0]
                raw.execute(f'UPDATE {table} SET valor_pago=?,data_pagamento=? WHERE id=?',(str(Decimal(total)/100),last,origin_id))
    return 1
