import os
import time
import subprocess

def iniciar():
    # 1. Cria a pasta e o arquivo inicial para nunca dar erro 404
    os.makedirs("stream", exist_ok=True)
    with open("stream/live.m3u8", "w") as f:
        f.write("#EXTM3U\n")

    # 2. Inicia o servidor HTTP em segundo plano imediatamente
    print("Iniciando servidor HTTP na porta 8080...")
    subprocess.Popen(["python3", "-m", "http.server", "8080", "--directory", "stream"])
    time.sleep(2)

    # 3. Liga o túnel do Serveo LOGO NO INÍCIO para fixar o link na tela sem travar
    print("Iniciando tunel de rede seguro e estavel...")
    subprocess.Popen([
        "ssh", "-o", "StrictHostKeyChecking=no", 
        "-R", "80:localhost:8080", "serveo.net"
    ])
    time.sleep(5) # Tempo para garantir que o link apareça nos logs

    # 4. Força a criação da tela virtual ativa ':99'
    os.system("Xvfb :99 -screen 0 1280x720x24 &")
    os.environ["DISPLAY"] = ":99"
    time.sleep(3) 

    # 5. Inicia o gravador FFmpeg em modo ultrafast
    ffmpeg_cmd = [
        "ffmpeg", "-f", "pulse", "-i", "default",
        "-f", "x11grab", "-draw_mouse", "0", "-video_size", "1280x720", "-i", ":99.0",
        "-c:v", "libx264", "-preset", "ultrafast", "-profile:v", "baseline", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k", "-g", "60", "-hls_time", "2", 
        "-hls_list_size", "5", "-hls_flags", "delete_segments", 
        "stream/live.m3u8"
    ]
    print("FFmpeg iniciando gravacao ultra rapida...")
    processo_ffmpeg = subprocess.Popen(ffmpeg_cmd)

    # 6. Só agora abrimos o navegador de forma separada
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        print("Ligando navegador na tela virtual externa...")
        browser = p.chromium.launch(headless=False, args=["--no-sandbox", "--disable-dev-shm-usage"])
        page = browser.new_page(viewport={"width": 1280, "height": 720})
        
        url_alvo = "https://ais-pre-czbrtxxjttcqeqhdn3kw3n-102718744012.us-east5.run.app/watch"
        print(f"Acessando o site: {url_alvo}")
        
        try:
            page.goto(url_alvo, wait_until="commit", timeout=0)
            print("Pagina conectada!")
            time.sleep(5)
            page.evaluate("document.documentElement.requestFullscreen()")
            time.sleep(2)
            page.mouse.click(640, 360)
        except Exception as e:
            print(f"Aviso no carregamento: {e}")

        # Mantém o streaming ativo continuamente
        try:
            while True:
                time.sleep(60)
        except KeyboardInterrupt:
            processo_ffmpeg.terminate()
            browser.close()

if __name__ == "__main__":
    iniciar()
