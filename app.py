import os
import time
import subprocess
import http.server
import socketserver
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

# 1. Configurar opções do Chrome para garantir renderização gráfica no ambiente virtual
chrome_options = Options()
chrome_options.add_argument('--no-sandbox')
chrome_options.add_argument('--disable-dev-shm-usage')
chrome_options.add_argument('--window-size=1280,720')
# Desativa aceleração de hardware que pode causar bugs de tela preta no Xvfb
chrome_options.add_argument('--disable-gpu')  
chrome_options.add_argument('--disable-software-rasterizer')

# 2. Inicializar o navegador e abrir o site ANTES de ligar o FFmpeg
print("Inicializando o navegador...")
driver = webdriver.Chrome(options=chrome_options)

# Ajusta a janela explicitamente para garantir que preencha a tela virtual (:99)
driver.set_window_size(1280, 720)

print("Acessando a página alvo...")
driver.get("https://ais-pre-czbrtxxjttcqeqhdn3kw3n-102718744012.us-east5.run.app/watch") # Substitua pela sua URL alvo

# PAUSA CRÍTICA: Espera 8 segundos para a página, imagens e scripts carregarem por completo
print("Aguardando renderização completa da página...")
time.sleep(8)

# 3. Comando FFmpeg corrigido para capturar a tela virtual ativa
# Adicionado "-draw_mouse 0" para não mostrar o ponteiro do mouse e otimizar
ffmpeg_cmd = [
    "ffmpeg", 
    "-f", "x11grab", 
    "-video_size", "1280x720", 
    "-i", ":99.0", # Captura a tela virtual onde o Chrome já está desenhado
    "-c:v", "libx264", 
    "-profile:v", "baseline", 
    "-pix_fmt", "yuv420p",
    "-g", "60", 
    "-hls_time", "2", 
    "-hls_list_size", "5", 
    "-hls_flags", "delete_segments", 
    "/app/stream/live.m3u8"
]

print("Iniciando gravação e codificação do streaming...")
subprocess.Popen(ffmpeg_cmd)

# 4. Criar o servidor Web interno na porta do Render
class StreamingServer(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        # Garante o funcionamento do link m3u8 em players externos de IPTV
        self.send_header('Access-Control-Allow-Origin', '*')
        super().end_headers()

def iniciar_servidor():
    os.chdir("/app/stream")
    porta = int(os.environ.get("PORT", 10000))
    with socketserver.TCPServer(("", porta), StreamingServer) as httpd:
        print(f"Servidor HTTP ativo na porta {porta}. Link pronto para transmissão!")
        httpd.serve_forever()

iniciar_servidor()
