import os
import subprocess
import threading
import http.server
import socketserver
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

# 1. Configurar o Chrome em segundo plano na tela virtual
chrome_options = Options()
chrome_options.add_argument('--no-sandbox')
chrome_options.add_argument('--disable-dev-shm-usage')
chrome_options.add_argument('--window-size=1280,720')
chrome_options.add_argument('--headless=new')  # Roda sem monitor físico

driver = webdriver.Chrome(options=chrome_options)
driver.get("https://google.com") # Substitua pela sua URL alvo

# 2. Comando FFmpeg para gravar a tela virtual e fragmentar em M3U8
ffmpeg_cmd = [
    "ffmpeg", "-f", "x11grab", "-video_size", "1280x720", "-i", ":99.0",
    "-c:v", "libx264", "-profile:v", "baseline", "-pix_fmt", "yuv420p",
    "-g", "60", "-hls_time", "2", "-hls_list_size", "5", 
    "-hls_flags", "delete_segments", "/app/stream/live.m3u8"
]
subprocess.Popen(ffmpeg_cmd)

# 3. Criar o servidor Web interno na porta exigida pelo Render
class StreamingServer(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        # Habilita CORS para o link m3u8 rodar em qualquer player de IPTV/VLC externos
        self.send_header('Access-Control-Allow-Origin', '*')
        super().end_headers()

def iniciar_servidor():
    os.chdir("/app/stream")
    # O Render exige escutar na porta 10000 ou na variável de ambiente $PORT
    porta = int(os.environ.get("PORT", 10000))
    with socketserver.TCPServer(("", porta), StreamingServer) as httpd:
        print(f"Servidor de streaming ativo na porta {porta}")
        httpd.serve_forever()

iniciar_servidor()
