import os
import sys
import django
import datetime
import shutil
import time
from django.core.mail import send_mail
from django.conf import settings


# --- 1️⃣ BACKUP DO BANCO ---
db_path = "/home/hidrogestao/hidrogestao/db.sqlite3"
backup_dir = "/home/hidrogestao/backups"
os.makedirs(backup_dir, exist_ok=True)

data = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M")
backup_file = os.path.join(backup_dir, f"backup_{data}.sqlite3")
shutil.copy(db_path, backup_file)
print(f"✅ Backup criado: {backup_file}")

# --- 2️⃣ LIMPEZA DE BACKUPS ANTIGOS ---
limite_dias = 10
agora = time.time()

for arquivo in os.listdir(backup_dir):
    caminho_arquivo = os.path.join(backup_dir, arquivo)
    if os.path.isfile(caminho_arquivo):
        idade_dias = (agora - os.path.getmtime(caminho_arquivo)) / 86400
        if idade_dias > limite_dias:
            os.remove(caminho_arquivo)
            print(f"🗑️ Backup removido: {arquivo}")


# --- 3️⃣ VERIFICAÇÃO DE EVENTOS (data_prevista = hoje) ---
# --- CONFIGURA DJANGO ---
sys.path.append('/home/hidrogestao/hidrogestao')
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "HIDROGestao.settings")
django.setup()

from gestao_contratos.models import Evento, ContratoTerceiros, User

hoje = datetime.date.today()
eventos_hoje = Evento.objects.filter(data_prevista=hoje)

for evento in eventos_hoje:
    contrato = evento.contrato_terceiro
    if contrato.status != 'encerrado':
        if contrato and contrato.coordenador and contrato.coordenador.email:
            coordenador = contrato.coordenador
            email_destino = coordenador.email
            print(f"👥 Usuário Coordenador: {email_destino}")
            assunto = f"Lembrete de entrega - Evento #{evento.id}"
            mensagem = (
                f"Olá {coordenador.first_name or coordenador.username},\n\n"
                f"Este é um lembrete automático para a entrega prevista hoje ({hoje.strftime('%d/%m/%Y')}).\n\n"
                f"Fornecedor: {evento.empresa_terceira}\n"
                f"Descrição: {evento.descricao}\n"
                f"Contrato: {contrato.num_contrato or 'N/A'}\n\n"
                f"Atenciosamente,\nSistema Hidrogestão"
            )
            try:
                send_mail(assunto, mensagem, "hidro.gestao25@gmail.com", [email_destino])
                print(f"📧 E-mail enviado para {email_destino} (Evento {evento.id})")
            except Exception as e:
                print(f"⚠️ Erro ao enviar e-mail para {email_destino}: {e}")

# --- 4️⃣ VERIFICAÇÃO DE CONTRATOS (data_fim = hoje) ---
contratos_hoje = ContratoTerceiros.objects.filter(data_fim=hoje)

# busca todos os usuários do grupo "suprimento"
usuarios_suprimento = User.objects.filter(grupo="suprimento").exclude(email__isnull=True).exclude(email="")
emails_suprimento = [u.email for u in usuarios_suprimento]
print(f"👥 Usuários suprimento: {emails_suprimento}")

for contrato in contratos_hoje:
    if contrato.status != 'encerrado':
        destinatarios = []

        # adiciona o e-mail do coordenador, se existir
        if contrato.coordenador and contrato.coordenador.email:
            destinatarios.append(contrato.coordenador.email)

        # adiciona todos os e-mails do grupo suprimento
        destinatarios.extend(emails_suprimento)

        # remove duplicados
        destinatarios = list(set(destinatarios))

        if not destinatarios:
            print(f"⚠️ Nenhum destinatário encontrado para contrato {contrato.id}")
            continue

        assunto = f"Encerramento de contrato - {contrato.empresa_terceira}"
        mensagem = (
            f"Olá,\n\n"
            f"O contrato nº {contrato.num_contrato or 'N/A'} referente ao projeto {contrato.cod_projeto} "
            f"com a empresa {contrato.empresa_terceira} encerra hoje ({hoje.strftime('%d/%m/%Y')}).\n\n"
            f"Por favor, verifique as providências necessárias.\n\n"
            f"Atenciosamente,\nSistema Hidrogestão"
        )
        try:
            send_mail(assunto, mensagem, "hidro.gestao25@gmail.com", destinatarios)
            print(f"📧 E-mail enviado: Contrato {contrato.id} -> {destinatarios}")
        except Exception as e:
            print(f"⚠️ Erro ao enviar e-mail para {destinatarios}: {e}")

print("✅ Rotina concluída com sucesso.")
