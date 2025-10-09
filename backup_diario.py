import datetime
import shutil
import os
import time

# Caminho do banco
db_path = "/home/hidrogestao/hidrogestao/db.sqlite3"

# Pasta de backups
backup_dir = "/home/hidrogestao/backups"

# Cria a pasta, se não existir
os.makedirs(backup_dir, exist_ok=True)

# Nome do arquivo de backup
data = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M")
backup_file = os.path.join(backup_dir, f"backup_{data}.sqlite3")

# Copia o banco de dados
shutil.copy(db_path, backup_file)
#print(f"✅ Backup criado: {backup_file}")

# --- LIMPEZA AUTOMÁTICA ---
# Tempo limite em dias
limite_dias = 10
agora = time.time()

for arquivo in os.listdir(backup_dir):
    caminho_arquivo = os.path.join(backup_dir, arquivo)
    if os.path.isfile(caminho_arquivo):
        idade_dias = (agora - os.path.getmtime(caminho_arquivo)) / 86400  # segundos -> dias
        if idade_dias > limite_dias:
            os.remove(caminho_arquivo)
            #print(f"🗑️ Backup antigo removido: {arquivo}")

#print("🧹 Limpeza concluída com sucesso!")
