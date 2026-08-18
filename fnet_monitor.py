"""
Monitor de documentos - Fundos.NET (B3/CVM) - MÚLTIPLOS FUNDOS
=================================================================

Verifica a lista de documentos de vários fundos no Fundos.NET e envia UM
alerta consolidado (via Telegram, ou só imprime no console) quando aparece
algo novo em qualquer um deles.

INSTALAÇÃO
----------
    pip install playwright requests
    playwright install chromium

CONFIGURAÇÃO
------------
1. Preencha o dicionário FUNDOS abaixo com "Nome que você quiser": "CNPJ".
   O CNPJ é só os números, sem pontuação (o mesmo que aparece na URL
   cnpjFundo=... do Fundos.NET).
2. (Opcional, mas recomendado) Configure alertas por Telegram:
   a. Fale com @BotFather no Telegram, crie um bot, copie o TOKEN.
   b. Mande uma mensagem qualquer pro seu bot.
   c. Acesse https://api.telegram.org/bot<SEU_TOKEN>/getUpdates no navegador
      e copie o "chat":{"id": ...} que aparecer — esse é o seu CHAT_ID.
   d. Defina as variáveis de ambiente TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID
      (ou cole os valores direto nas constantes abaixo).

USO
---
    python fnet_monitor.py            # roda uma vez, checando todos os fundos
    python fnet_monitor.py --loop     # fica rodando, checando a cada 2h

Para rodar sem deixar o computador ligado o tempo todo, agende com:

  Windows (Agendador de Tarefas):
    - Criar tarefa básica > Disparar "Diariamente", repetir a cada 2 horas
    - Ação: iniciar programa "python" com argumento "C:\\caminho\\fnet_monitor.py"

  Linux/Mac (cron):
    - crontab -e
    - adicionar a linha:  0 */2 * * * /usr/bin/python3 /caminho/fnet_monitor.py
"""

import json
import os
import sys
import time

import requests
from playwright.sync_api import sync_playwright

# ---------- CONFIGURAÇÃO: SEUS 14 FUNDOS ----------
# Preencha com "Nome": "CNPJ" (só números). Exemplo com o fundo do seu print:
FUNDOS = {
    "Guardian Real Estate": "37295919000160",
    "BTLG11 (BTG Pactual Logistica)": "11839593000109",
    "GGRC11 (GGR Covepi Renda)": "26614291000100",
    "Fundo GTWR11": "23740527000158",  # renomeie como preferir
    "Fundo HSLG11": "32903621000171",
    "Fundo MXRF11": "97521225000125",
    "Fundo KNCR11": "16706958000132",
    "Fundo RZAK11": "36642219000131",
    "Fundo RZAT11": "28267696000136",
    "Fundo RZTR11": "36501128000186",
    "Fundo XPLG11": "26502794000185",
    "Fundo TRXF11": "28548288000152",
    "Fundo PORD11": "17156502000109",
    "Fundo HGLG11": "11728688000147",
}

CHECK_INTERVAL_SECONDS = 2 * 60 * 60  # usado só no modo --loop

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8637115135:AAHdYtZTZ2hCL7R5kiLepU1QI8phBkJvqvA")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "224555976")
# ----------------------------------------------------

STATE_DIR = "fnet_state"


def url_for(cnpj: str) -> str:
    return f"https://fnet.bmfbovespa.com.br/fnet/publico/abrirGerenciadorDocumentosCVM?cnpjFundo={cnpj}"


def state_file_for(cnpj: str) -> str:
    os.makedirs(STATE_DIR, exist_ok=True)
    return os.path.join(STATE_DIR, f"{cnpj}.json")


def send_alert(message: str):
    print(message)
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": message}, timeout=10)
    except Exception as e:
        print(f"[erro] Falha ao enviar alerta pelo Telegram: {e}")


def fetch_documents(page, cnpj: str):
    page.goto(url_for(cnpj), wait_until="networkidle", timeout=30000)
    try:
        page.wait_for_selector("table tbody tr", timeout=20000)
    except Exception:
        return []

    rows = page.query_selector_all("table tbody tr")
    documents = []
    for row in rows:
        cells = [c.inner_text().strip() for c in row.query_selector_all("td")]
        if cells:
            documents.append(" | ".join(cells))
    return documents


def load_previous_state(cnpj: str):
    path = state_file_for(cnpj)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def save_state(cnpj: str, documents):
    with open(state_file_for(cnpj), "w", encoding="utf-8") as f:
        json.dump(documents, f, ensure_ascii=False, indent=2)


def check_all_funds():
    if not FUNDOS:
        print("[erro] O dicionário FUNDOS está vazio. Adicione seus fundos no topo do script.")
        return

    resumo_alertas = []  # texto por fundo com documentos novos
    erros = []

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()

        for nome, cnpj in FUNDOS.items():
            try:
                current = fetch_documents(page, cnpj)

                if not current:
                    erros.append(f"{nome} (CNPJ {cnpj}): não consegui ler a tabela de documentos.")
                    continue

                previous = load_previous_state(cnpj)

                if previous is None:
                    save_state(cnpj, current)
                    print(f"[{nome}] Estado inicial salvo com {len(current)} documento(s).")
                    continue

                new_entries = [d for d in current if d not in previous]

                if new_entries:
                    linhas = []
                    for d in new_entries[:5]:
                        partes = d.split(" | ")
                        linhas.append(f"  - {partes[0][:60]}" + (f" ({partes[1]})" if len(partes) > 1 else ""))
                    resumo_alertas.append(f"📄 {nome} — {len(new_entries)} novo(s):\n" + "\n".join(linhas))
                else:
                    print(f"[{nome}] Nenhuma mudança.")

                save_state(cnpj, current)

            except Exception as e:
                erros.append(f"{nome} (CNPJ {cnpj}): erro ao checar — {e}")

        browser.close()

    if resumo_alertas:
        mensagem = "ANÁLISE GITHUB:🔔 Novos documentos no Fundos.NET:\n\n" + "\n\n".join(resumo_alertas)
        send_alert(mensagem)

    elif not erros:
        mensagem = (
            "ANÁLISE GITHUB: ✅ Varredura concluída.\n\n"
            "Nenhuma alteração detectada no Fundos.NET."
        )
        send_alert(mensagem)

    if erros:
        print("\n[avisos]")
        for e in erros:
            print(f" - {e}")


if __name__ == "__main__":
    if "--loop" in sys.argv:
        print(f"Rodando em loop, checando {len(FUNDOS)} fundo(s) a cada {CHECK_INTERVAL_SECONDS/3600:.0f}h. Ctrl+C para parar.")
        while True:
            check_all_funds()
            time.sleep(CHECK_INTERVAL_SECONDS)
    else:
        check_all_funds()
