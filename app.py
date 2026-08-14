import os
import time
import subprocess

def iniciar():
    # 1. Prepara a pasta de streaming e cria o arquivo base para evitar erro 404
    os.makedirs("stream", exist_ok=True)
    with open("stream/live.m3u8", "w") as f:
        f.write("#EXTM3U\n")

    # 2. Inicia o servidor HTTP em segundo plano imediatamente
    print("Iniciando servidor HTTP na porta 8080...")
    subprocess.Popen(["python3", "-m", "http.server", "8080", "--directory", "stream"])
    time.sleep(2)

    # 3. Liga a ponte de internet oficial do sistema (Sem Ngrok, sem travas)
    print("Iniciando tunel de rede seguro e estavel...")
    subprocess.Popen([
        "ssh", "-o", "StrictHostKeyChecking=no", "-o", "ServerAliveInterval=60",
        "-R", "80:localhost:8080", "nokey@localhost.run"
    ])
    time.sleep(5)

    print("\n==========================================================")
    print("======== SEU STREAMING FOI INICIADO COM SUCESSO ========")
    print("Suba a tela do log para copiar o seu endereço .lhr.life")
    print("==========================================================\n")

    # 4. Configura a tela virtual em alta definição
    os.system("Xvfb :99 -screen 0 1280x720x24 &")
    os.environ["DISPLAY"] = ":99"
    time.sleep(3) 

    # 5. FFmpeg captura a tela virtual :99.0 completa, com áudio nativo e sem o mouse
    ffmpeg_cmd = [
        "ffmpeg", "-f", "pulse", "-i", "auto_null.monitor",
        "-f", "x11grab", "-draw_mouse", "0", "-video_size", "1280x720", "-i", ":99.0",
        "-c:v", "libx264", "-preset", "ultrafast", "-profile:v", "baseline", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-g", "60", "-hls_time", "2", 
        "-hls_list_size", "5", "-hls_flags", "delete_segments", 
        "stream/live.m3u8"
    ]
    print("FFmpeg iniciando gravacao continua...")
    processo_ffmpeg = subprocess.Popen(ffmpeg_cmd)

    # 6. Inicializa o navegador focado
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        print("Ligando navegador interativo em Modo Quiosque...")
        browser = p.chromium.launch(
            headless=False, 
            args=[
                "--no-sandbox", 
                "--disable-dev-shm-usage",
                "--autoplay-policy=no-user-gesture-required",
                "--kiosk",                     
                "--fill-properties",
                "--no-first-run",
                "--no-default-browser-check",
                "--start-fullscreen"  
            ]
        )
        page = browser.new_page(viewport={"width": 1280, "height": 720})
        
        url_alvo = "https://ais-pre-czbrtxxjttcqeqhdn3kw3n-102718744012.us-east5.run.app/watch"
        print(f"Acessando o site: {url_alvo}")
        
        try:
            page.goto(url_alvo, wait_until="commit", timeout=0)
            
            # === SUA SOLICITAÇÃO: AGUARDA INICIAR E DÁ O TOQUE NO MEIO ===
            print("Aguardando 15 segundos para a transmissao estabilizar...")
            time.sleep(15) 
            
            # Injeta o escutador de cliques nativo do navegador
            page.evaluate("""
                document.addEventListener('click', () => {
                    let video = document.querySelector('video');
                    if (video) {
                        video.requestFullscreen().catch(e => {});
                    } else {
                        let iframes = document.querySelectorAll('iframe');
                        for (let i = 0; i < iframes.length; i++) {
                            try {
                                let innerVideo = iframes[i].contentWindow.document.querySelector('video');
                                if (innerVideo) innerVideo.requestFullscreen().catch(e => {});
                            } catch(e) {}
                        }
                    }
                }, { once: true });
            """)
            time.sleep(1)
            
            # Executa o movimento simulado e o clique físico de ativacao no meio exato da tela (640, 360)
            print("Dando o toque no meio da tela pós-inicio para destravar a tela cheia...")
            page.mouse.move(100, 100)
            time.sleep(0.5)
            page.mouse.move(640, 360)
            time.sleep(0.5)
            page.mouse.click(640, 360)
            print("Toque executado com sucesso.")
            time.sleep(2)
            
        except Exception as e:
            print(f"Aviso inicial: {e}")

        # === VIGIA INTELIGENTE DE RECONEXÃO ===
        print("Vigia de troca de videos ativo...")
        try:
            while True:
                time.sleep(5)
                try:
                    is_fullscreen = page.evaluate("""
                        let mainFS = !!document.fullscreenElement;
                        if (mainFS) return true;
                        let iframes = document.querySelectorAll('iframe');
                        for (let i = 0; i < iframes.length; i++) {
                            try {
                                if (!!iframes[i].contentWindow.document.fullscreenElement) return true;
                            } catch(e) {}
                        }
                        return false;
                    """)
                    
                    if not is_fullscreen:
                        print("Troca de video ou perda de tela cheia detectada. Reaplicando o toque...")
                        page.evaluate("""
                            document.addEventListener('click', () => {
                                let video = document.querySelector('video');
                                if (video) video.requestFullscreen().catch(e => {});
                                let iframes = document.querySelectorAll('iframe');
                                for (let i = 0; i < iframes.length; i++) {
                                    try {
                                        let innerVideo = iframes[i].contentWindow.document.querySelector('video');
                                        if (innerVideo) innerVideo.requestFullscreen().catch(e => {});
                                    } catch(e) {}
                                }
                            }, { once: true });
                        """)
                        time.sleep(0.5)
                        page.mouse.move(640, 360)
                        time.sleep(0.2)
                        page.mouse.click(640, 360)
                except:
                    pass
        except KeyboardInterrupt:
            processo_ffmpeg.terminate()
            browser.close()

if __name__ == "__main__":
    iniciar()
