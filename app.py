import os
import time
import subprocess
from playwright.sync_api import sync_playwright

def iniciar():
    # 1. Prepara as pastas do projeto
    os.makedirs("stream", exist_ok=True)
    with open("stream/live.m3u8", "w") as f:
        f.write("#EXTM3U\n")

    # 2. Configura o Token do Ngrok para liberar o link público
    # COLE O SEU TOKEN DO NGROK ENTRE AS ASPAS ABAIXO:
    TOKEN_NGROK = "SEU_TOKEN_AQUI"
    
    print("Iniciando tunel seguro com Ngrok...")
    os.system(f"pip install pyngrok")
    from pyngrok import ngrok
    ngrok.set_auth_token(TOKEN_NGROK)
    
    # Abre o túnel principal na porta 8080 para a live e o painel de controle
    url_publica = ngrok.connect(8080).public_url
    
    print("\n==========================================================")
    print("========= SEU LINK DE TRANSMISSÃO (IPTV/VLC) =========")
    print(f"{url_publica}/live.m3u8")
    print("==========================================================")
    print("========= PAINEL DE CONTROLE (ABRA NO NAVEGADOR) =========")
    print("Para interagir com a tela e ativar o botão de tela cheia,")
    print("copie o link abaixo, tire o '/live.m3u8' e mude a porta para ver a tela:")
    print(f"Acesse o painel do Ngrok para ver o status.")
    print("==========================================================\n")

    # 3. Inicia o servidor HTTP em segundo plano
    subprocess.Popen(["python3", "-m", "http.server", "8080", "--directory", "stream"])
    time.sleep(2)

    # 4. Configura a tela virtual em alta definição
    os.system("Xvfb :99 -screen 0 1280x720x24 &")
    os.environ["DISPLAY"] = ":99"
    time.sleep(3) 

    # 5. FFmpeg captura a tela virtual :99.0 limpa e sem o mouse
    ffmpeg_cmd = [
        "ffmpeg", "-f", "pulse", "-i", "auto_null.monitor",
        "-f", "x11grab", "-draw_mouse", "0", "-video_size", "1280x720", "-i", ":99.0",
        "-c:v", "libx264", "-preset", "ultrafast", "-profile:v", "baseline", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-g", "60", "-hls_time", "2", 
        "-hls_list_size", "5", "-hls_flags", "delete_segments", 
        "stream/live.m3u8"
    ]
    print("FFmpeg iniciando gravacao em tempo real...")
    processo_ffmpeg = subprocess.Popen(ffmpeg_cmd)

    # 6. Inicializa o navegador focado
    with sync_playwright() as p:
        print("Ligando navegador no modo interativo...")
        browser = p.chromium.launch(
            headless=False, 
            args=[
                "--no-sandbox", 
                "--disable-dev-shm-usage",
                "--autoplay-policy=no-user-gesture-required"
            ]
        )
        page = browser.new_page(viewport={"width": 1280, "height": 720})
        
        url_alvo = "https://ais-pre-czbrtxxjttcqeqhdn3kw3n-102718744012.us-east5.run.app/watch"
        print(f"Acessando o site: {url_alvo}")
        
        try:
            page.goto(url_alvo, wait_until="commit", timeout=0)
            time.sleep(10)
            
            # Tenta dar o primeiro clique automático de segurança
            page.mouse.click(640, 360)
            print("Navegador pronto e transmitindo.")
        except Exception as e:
            print(f"Aviso inicial: {e}")

        # Mantém a live aberta continuamente
        try:
            while True:
                time.sleep(60)
        except KeyboardInterrupt:
            processo_ffmpeg.terminate()
            browser.close()

if __name__ == "__main__":
    iniciar()
