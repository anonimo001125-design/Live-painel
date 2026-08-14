import os
import time
import subprocess

def iniciar():
    # 1. Prepara a pasta de streaming
    os.makedirs("stream", exist_ok=True)
    with open("stream/live.m3u8", "w") as f:
        f.write("#EXTM3U\n")

    # 2. Inicia o servidor HTTP em segundo plano
    print("Iniciando servidor HTTP na porta 8080...")
    subprocess.Popen(["python3", "-m", "http.server", "8080", "--directory", "stream"])
    time.sleep(2)

    # 3. Liga o túnel do Serveo
    print("Iniciando tunel de rede seguro e estavel...")
    subprocess.Popen([
        "ssh", "-o", "StrictHostKeyChecking=no", 
        "-R", "80:localhost:8080", "serveo.net"
    ])
    time.sleep(5)

    # 4. Configura a tela virtual em alta definição para o corte funcionar perfeitamente
    os.system("Xvfb :99 -screen 0 1280x720x24 &")
    os.environ["DISPLAY"] = ":99"
    time.sleep(3) 

    # 5. FFmpeg COM CORTADOR DE LENTE (CROP) ATIVADO
    # O filtro "-vf crop=1000:562:140:100" diz para a gravação:
    # "Corte uma janela de 1000x562 pixels, ignorando os primeiros 140 pixels da esquerda e os 100 pixels de aba do topo"
    # Depois ele estica o resultado de volta para 1280x720 para o seu player receber em tela cheia pura!
    ffmpeg_cmd = [
        "ffmpeg", "-f", "pulse", "-i", "auto_null.monitor",
        "-f", "x11grab", "-draw_mouse", "0", "-video_size", "1280x720", "-i", ":99.0",
        "-vf", "crop=1024:576:128:90,scale=1280:720", 
        "-c:v", "libx264", "-preset", "ultrafast", "-profile:v", "baseline", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-g", "60", "-hls_time", "2", 
        "-hls_list_size", "5", "-hls_flags", "delete_segments", 
        "stream/live.m3u8"
    ]
    print("FFmpeg iniciando gravacao com corte de bordas e abas automático...")
    processo_ffmpeg = subprocess.Popen(ffmpeg_cmd)

    # 6. Inicializa o navegador padrão
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        print("Ligando navegador no modo padrão estabilizado...")
        
        browser = p.chromium.launch(
            headless=False, 
            args=[
                "--no-sandbox", 
                "--disable-dev-shm-usage",
                "--autoplay-policy=no-user-gesture-required"
            ]
        )
        # Abre a janela do navegador esticada no tamanho máximo do servidor
        page = browser.new_page(viewport={"width": 1280, "height": 720})
        
        url_alvo = "https://ais-pre-czbrtxxjttcqeqhdn3kw3n-102718744012.us-east5.run.app/watch"
        print(f"Acessando o site: {url_alvo}")
        
        try:
            page.goto(url_alvo, wait_until="commit", timeout=0)
            time.sleep(12) # Tempo para o vídeo começar a rodar sozinho de fundo
            
            # Clica no centro da tela apenas para garantir que o som e o play fiquem ativos
            page.mouse.click(640, 360)
            print("Clique de ativação de áudio concluído.")
        except Exception as e:
            print(f"Aviso inicial: {e}")

        # === MONITOR DE RECONEXÃO CONTINUO ===
        print("Transmissão com corte inteligente ativa...")
        try:
            while True:
                time.sleep(10)
                try:
                    # Apenas mantém o foco dando cliques caso o site troque de episódio e pause
                    page.mouse.click(640, 360)
                except:
                    pass
        except KeyboardInterrupt:
            processo_ffmpeg.terminate()
            browser.close()

if __name__ == "__main__":
    iniciar()
