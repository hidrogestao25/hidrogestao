"""Decisões distintas nos dois contratos; preserva triggers e dados históricos."""
from django.conf import settings
from django.db import migrations,models
import django.db.models.deletion

B='gestao_contratos_bm'
SIDES=('documental','financeiro')
FIELDS=[]
for side in SIDES:
    FIELDS.extend([(f'status_lider_{side}','varchar(20)'),
        (f'aprovador_lider_{side}_id','bigint REFERENCES gestao_contratos_user(id) DEFERRABLE INITIALLY DEFERRED'),
        (f'data_lider_{side}','datetime'),(f'justificativa_lider_{side}','text')])
NAMES=('hidro_bm_dual_insert','hidro_bm_dual_decision','hidro_bm_dual_revision','hidro_bm_dual_director','hidro_pagamento_dual_bm','hidro_evento_dual_revision')
def shared(alias):return f"({alias}.evento_id IS NOT NULL AND {alias}.contrato_id IS NOT (SELECT contrato_terceiro_id FROM gestao_contratos_evento WHERE id={alias}.evento_id))"
def complete(alias):return ' AND '.join(f"{alias}.status_lider_{s}='aprovado' AND {alias}.aprovador_lider_{s}_id IS NOT NULL AND {alias}.data_lider_{s} IS NOT NULL" for s in SIDES)
def clear(alias):return ' AND '.join(f'{alias}.{f} IS NULL' for f,_ in FIELDS)
RELEVANT=('contrato_id','evento_id','os_id','numero_bm','parcela_paga','valor_pago','data_pagamento','data_inicial_medicao','data_final_medicao','arquivo_bm')
def reset_sql():
    return ','.join([f'{f}=NULL' for f,_ in FIELDS]+[f"{f}='pendente'" for f in ('status_coordenador','status_gerente','aprovacao_pagamento')]+[
        f'{f}=NULL' for f in ('data_aprovacao_coordenador','data_aprovacao_gerente','data_aprovacao_diretor',
        'justificativa_reprovacao_coordenador','justificativa_reprovacao_gerente','justificativa_reprovacao_diretor','justificativa_aprovacao_diretor')])

def create(apps,editor):
    if editor.connection.vendor!='sqlite':raise RuntimeError('Homologue a aprovação dupla para este motor antes de migrar.')
    # ALTER ADD nullable mantém os 31 gatilhos existentes, sem reconstrução da tabela.
    for field,kind in FIELDS:editor.execute(f'ALTER TABLE {B} ADD COLUMN {field} {kind} NULL')
    editor.execute(f"CREATE TRIGGER hidro_bm_dual_insert BEFORE INSERT ON {B} WHEN NOT({clear('NEW')}) BEGIN SELECT RAISE(ABORT,'Cadastre o BM antes de registrar decisões dos líderes.'); END")
    changed=' OR '.join(f'OLD.{f} IS NOT NEW.{f}' for f,_ in FIELDS)
    clauses=[]
    actor="json_extract(hidro_financial_context(),'$.usuario_id')"
    for side in SIDES:
        contract='NEW.contrato_id' if side=='documental' else '(SELECT contrato_terceiro_id FROM gestao_contratos_evento WHERE id=NEW.evento_id)'
        leader=f'(SELECT CASE WHEN c.guarda_chuva=1 AND c.cod_projeto_id IS NOT NULL THEN p.lider_contrato_id ELSE c.lider_contrato_id END FROM gestao_contratos_contratoterceiros c LEFT JOIN gestao_contratos_contrato p ON p.id=c.cod_projeto_id WHERE c.id={contract})'
        modified=' OR '.join(f'OLD.{f} IS NOT NEW.{f}' for f,_ in FIELDS if f.endswith(side) or f.endswith(side+'_id'))
        clauses.append(f'''SELECT CASE WHEN ({modified}) AND (OLD.status_lider_{side} IS NOT NULL
          OR NEW.status_lider_{side} IS NULL OR NEW.status_lider_{side} NOT IN ('aprovado','reprovado')
          OR NEW.aprovador_lider_{side}_id IS NOT {actor} OR {actor} IS NOT {leader}
          OR NOT EXISTS(SELECT 1 FROM gestao_contratos_user WHERE id={actor} AND is_active=1 AND grupo IN ('lider_contrato','gerente_lider','gerente_contrato'))
          OR NEW.data_lider_{side} IS NULL OR (NEW.status_lider_{side}='reprovado' AND coalesce(trim(NEW.justificativa_lider_{side}),'')=''))
          THEN RAISE(ABORT,'Decisão exige o líder do respectivo contrato e não pode ser reescrita.') END;''')
    editor.execute(f"CREATE TRIGGER hidro_bm_dual_decision BEFORE UPDATE ON {B} WHEN ({changed}) AND NOT({clear('NEW')}) BEGIN SELECT CASE WHEN NOT({shared('NEW')}) THEN RAISE(ABORT,'Aprovação dupla exige contratos distintos.') END; {''.join(clauses)} END")
    material=' OR '.join(f'OLD.{f} IS NOT NEW.{f}' for f in RELEVANT)
    editor.execute(f"CREATE TRIGGER hidro_bm_dual_revision AFTER UPDATE ON {B} WHEN ({material}) AND ({shared('OLD')} OR {shared('NEW')}) BEGIN UPDATE {B} SET {reset_sql()} WHERE id=NEW.id; END")
    editor.execute(f"CREATE TRIGGER hidro_bm_dual_director BEFORE UPDATE ON {B} WHEN NEW.aprovacao_pagamento='aprovado' AND OLD.aprovacao_pagamento IS NOT NEW.aprovacao_pagamento AND {shared('NEW')} AND NOT(coalesce(({complete('NEW')}),0)) BEGIN SELECT RAISE(ABORT,'BM compartilhado exige as duas aprovações dos líderes.'); END")
    editor.execute(f"""CREATE TRIGGER hidro_pagamento_dual_bm BEFORE INSERT ON gestao_contratos_pagamentonf
      WHEN NEW.tipo='pagamento' AND NEW.origem_registro!='legado_nf_integral' AND EXISTS(
        SELECT 1 FROM gestao_contratos_nf n JOIN {B} b ON b.id=n.bm_id WHERE n.id=NEW.nf_id AND {shared('b')} AND NOT(coalesce(({complete('b')}),0)))
      BEGIN SELECT RAISE(ABORT,'BM compartilhado exige as duas aprovações dos líderes.'); END""")
    editor.execute(f"CREATE TRIGGER hidro_evento_dual_revision AFTER UPDATE OF contrato_terceiro_id ON gestao_contratos_evento WHEN OLD.contrato_terceiro_id IS NOT NEW.contrato_terceiro_id BEGIN UPDATE {B} SET {reset_sql()} WHERE evento_id=NEW.id AND (contrato_id IS NOT NEW.contrato_terceiro_id OR contrato_id IS NOT OLD.contrato_terceiro_id); END")

def remove(apps,editor):
    if editor.connection.cursor().execute(f'SELECT 1 FROM {B} WHERE NOT({clear(B)}) LIMIT 1').fetchone():
        raise RuntimeError('Há decisões de liderança: reversão destrutiva não autorizada.')
    for name in reversed(NAMES):editor.execute(f'DROP TRIGGER {name}')
    for field,_ in reversed(FIELDS):editor.execute(f'ALTER TABLE {B} DROP COLUMN {field}')

state=[]
for side in SIDES:
    state.extend([
        migrations.AddField(model_name='bm',name=f'status_lider_{side}',field=models.CharField(max_length=20,choices=[('pendente','Pendente'),('aprovado','Aprovado'),('reprovado','Reprovado')],null=True,blank=True,editable=False)),
        migrations.AddField(model_name='bm',name=f'aprovador_lider_{side}',field=models.ForeignKey(to=settings.AUTH_USER_MODEL,on_delete=django.db.models.deletion.PROTECT,null=True,blank=True,related_name='+',db_index=False,editable=False)),
        migrations.AddField(model_name='bm',name=f'data_lider_{side}',field=models.DateTimeField(null=True,blank=True,editable=False)),
        migrations.AddField(model_name='bm',name=f'justificativa_lider_{side}',field=models.TextField(null=True,blank=True,editable=False)),
    ])
class Migration(migrations.Migration):
    dependencies=[('gestao_contratos','0126_os_identidade_financeira')]
    operations=[migrations.SeparateDatabaseAndState(database_operations=[migrations.RunPython(create,remove)],state_operations=state)]
