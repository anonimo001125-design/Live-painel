import os
import time
import subprocess
import http.server
import socketserver
from playwright.sync_api import sync_playwright

def rodar_streaming():
    with sync_playwright() as p:
        print("Inicializando o navegador leve (Estilo Duck/WebKit)...")
        # Abre o navegador simulando um ambiente real com áudio liberado
        browser = p.webkit.launch(headless=False, args=["--window-size=1280,720"])
        
        # Cria o contexto permitindo áudio tocar sozinho sem travas
        context = browser.new_context(
            viewport={"width": 1280, "height": 720},
            ignore_https_errors=True
        )
        
        page = context.new_page()
        
        # URL DO SEU SITE: Altere o link abaixo para a sua página real
        url_alvo = "https://google.com"
        print(f"Acessando: {url_alvo}")
        page.goto(url_alvo, wait_until="networkidle")
        
        # Aguarda um momento para estabilização visual da tela
        time.sleep(5)
        
        # Inicia a captura de áudio (pulse) e tela (:99) com o FFmpeg
        ffmpeg_cmd = [
            "ffmpeg",
            "-f", "pulse", "-i", "default",
            "-f", "x11grab", "-video_size", "1280x720", "-i", ":99.0",
            "-c:v", "libx264", "-profile:v", "baseline", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k",
            "-g", "60", "-hls_time", "2", "-hls_list_size", "5", 
            "-hls_flags", "delete_segments", "/app/stream/live.m3u8"
        ]
        
        print("Iniciando codificação de áudio e vídeo em tempo real...")
        processo_ffmpeg = subprocess.Popen(ffmpeg_cmd)
        
        # Cria o servidor HTTP para disponibilizar o arquivo na Web para o Render
        class StreamingServer(http.server.SimpleHTTPRequestHandler):
            def end_headers(self):
                self.send_header('Access-Control-Allow-Origin', '*')
                super().end_headers()

        os.chdir("/app/stream")
        porta = int(os.environ.get("PORT", 10000))
        
        with socketserver.TCPServer(("", porta), StreamingServer) as httpd:
            print(f"Streaming ativo com sucesso! Porta: {porta}")
            # Mantém o script vivo transmitindo para sempre
            try:
                httpd.serve_forever()
            except KeyboardInterrupt:
                processo_ffmpeg.terminate()
                browser.close()

if __name__ == "__main__":
    rodar_streaming()
