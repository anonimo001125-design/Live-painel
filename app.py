import os
import subprocess
import threading
import time
import shutil
from flask import Flask, send_from_directory

app = Flask(__name__)

# CONFIGURAÇÕES ADAPTADAS PARA O RENDER
URL_ALVO = "https://ais-pre-czbrtxxjttcqeqhdn3kw3n-102718744012.us-east5.run.app/watch"
OUTPUT_DIR = os.path.join(os.getcwd(), "static", "hls") # Pasta correta mapeada no Dockerfile
CHROME_PROFILE = "/tmp/perfil_limpo_total"

def faxina_seguranca():
    while True:
        try:
            if os.path.exists(OUTPUT_DIR):
                os.system(f"find {OUTPUT_DIR} -name '*.ts' -mmin +0.3 -delete 2>/dev/null")
        except: pass
        time.sleep(10)

def rodar_servicos():
    while True:
        try:
            # 1. LIMPEZA TOTAL
            os.system("pkill -9 -f chromium")
            os.system("pkill -9 -f ffmpeg")
            os.system("pkill -9 -f Xvfb")
            os.system("pkill -9 -f pulseaudio")
            
            shutil.rmtree(CHROME_PROFILE, ignore_errors=True)
            shutil.rmtree(OUTPUT_DIR, ignore_errors=True)
            os.makedirs(OUTPUT_DIR, exist_ok=True)
            time.sleep(2)

            # 2. MONITOR VIRTUAL (Gerenciado unicamente aqui no script)
            subprocess.Popen(["Xvfb", ":99", "-ac", "-screen", "0", "854x480x24", "-nocursor"])
            time.sleep(2)
            os.environ["DISPLAY"] = ":99"

            # 3. ÁUDIO
            os.system("pulseaudio --start --exit-idle-time=-1")
            time.sleep(2)
            os.system("pactl load-module module-null-sink sink_name=audio_sink")
            os.environ["PULSE_SINK"] = "audio_sink"

            # 4. NAVEGADOR (MODO LIMPO)
            chrome_cmd = [
                "chromium", "--display=:99", "--no-sandbox", "--disable-gpu",
                "--disable-dev-shm-usage", "--window-size=854,480",
                "--window-position=0,0", "--app=" + URL_ALVO,
                "--autoplay-policy=no-user-gesture-required",
                "--disable-session-crashed-bubble",
                "--disable-infobars",
                f"--user-data-dir={CHROME_PROFILE}"
            ]
            subprocess.Popen(chrome_cmd)
            
            # Espera o site carregar completamente
            time.sleep(60) 
            
            # --- LIMPEZA DE TELA (Cliques Cirúrgicos baseados no print que você enviou) ---
            # 1. Clica no botão "Close and continue" ou "Grant permission" caso apareçam travas de Cookie
            os.system("xdotool mousemove 427 300 click 1")
            time.sleep(2)
            # 2. Clica no centro para garantir o Play/Som do player
            os.system("xdotool mousemove 427 240 click 1")
            time.sleep(1)
            # 3. Esconde o mouse totalmente fora da área de visão
            os.system("xdotool mousemove 900 500")

            # 5. FFMPEG (GRAVAÇÃO LIMPA SEM SETA)
            ffmpeg_cmd = [
                'ffmpeg',
                '-f', 'x11grab', '-draw_mouse', '0', '-s', '854x480', '-framerate', '24', '-i', ':99.0',
                '-f', 'pulse', '-ac', '2', '-i', 'audio_sink.monitor',
                '-c:v', 'libx264', '-preset', 'ultrafast', '-tune', 'zerolatency',
                '-pix_fmt', 'yuv420p', '-b:v', '850k', 
                '-c:a', 'aac', '-b:a', '128k',
                '-f', 'hls', '-hls_time', '4', '-hls_list_size', '3',
                '-hls_flags', 'delete_segments+temp_file',
                os.path.join(OUTPUT_DIR, 'live.m3u8')
            ]
            
            p_ffmpeg = subprocess.Popen(ffmpeg_cmd)
            p_ffmpeg.wait() 
            
        except Exception:
            time.sleep(5)

@app.route('/')
def index():
    return "<h1>Transmissão Ativa no Render</h1><p>Buscando sinal do site alvo...</p>"

# Rota corrigida para ler os arquivos de dentro de static/hls
@app.route('/stream/<path:filename>')
def serve_hls(filename):
    return send_from_directory(OUTPUT_DIR, filename)

if __name__ == "__main__":
    # Captura a porta dinâmica que o Render fornece obrigatoriamente
    port_render = int(os.environ.get("PORT", 5000))
    
    threading.Thread(target=rodar_servicos, daemon=True).start()
    threading.Thread(target=faxina_seguranca, daemon=True).start()
    app.run(host='0.0.0.0', port=port_render)
