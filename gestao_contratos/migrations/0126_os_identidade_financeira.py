"""Protege OS com BM/NF, inclusive em UPDATE em lote e SQL direto."""
from django.db import migrations


NAME = "hidro_os_financial_identity"
SQL = f"""CREATE TRIGGER {NAME}
BEFORE UPDATE OF contrato_id, cod_projeto_id, solicitacao_id ON gestao_contratos_os
WHEN (OLD.contrato_id IS NOT NEW.contrato_id
   OR OLD.cod_projeto_id IS NOT NEW.cod_projeto_id
   OR OLD.solicitacao_id IS NOT NEW.solicitacao_id)
AND (EXISTS(SELECT 1 FROM gestao_contratos_bm WHERE os_id=OLD.id)
  OR EXISTS(SELECT 1 FROM gestao_contratos_nf WHERE os_id=OLD.id))
BEGIN
 SELECT RAISE(ABORT,'OS com BM/NF: identidade financeira permanente; transferencia automatica proibida.');
END"""


def create(apps, schema_editor):
    if schema_editor.connection.vendor != "sqlite":
        raise RuntimeError("Homologue proteção de identidade financeira equivalente para este banco.")
    schema_editor.execute(SQL)
    # Fecha a outra ordem de commit da corrida: uma OS ainda sem BM pode ser
    # transferida, mas um BM baseado no contrato anterior não pode entrar depois.
    for operation, suffix in (("INSERT", "insert"), ("UPDATE OF os_id, contrato_id", "update")):
        schema_editor.execute(f"""CREATE TRIGGER hidro_bm_os_contract_{suffix}
        BEFORE {operation} ON gestao_contratos_bm
        WHEN NEW.os_id IS NOT NULL AND NEW.contrato_id IS NOT
          (SELECT contrato_id FROM gestao_contratos_os WHERE id=NEW.os_id)
        BEGIN SELECT RAISE(ABORT,'A OS deve pertencer ao contrato do BM.'); END""")


def remove(apps, schema_editor):
    schema_editor.execute(f"DROP TRIGGER {NAME}")
    for suffix in ("insert", "update"):
        schema_editor.execute(f"DROP TRIGGER hidro_bm_os_contract_{suffix}")


class Migration(migrations.Migration):
    dependencies = [("gestao_contratos", "0125_arquivamento_os_aditivos")]
    operations = [migrations.RunPython(create, remove)]
