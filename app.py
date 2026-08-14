import os
import time
import subprocess
import json
import urllib.request

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
    # Salva os logs do túnel em um arquivo temporario para podermos ler o endereço depois
    with open("tunnel.log", "w") as log_file:
        subprocess.Popen([
            "ssh", "-o", "StrictHostKeyChecking=no", 
            "-R", "80:localhost:8080", "serveo.net"
        ], stdout=log_file, stderr=log_file)
    time.sleep(5)

    # 4. Configura a tela virtual em alta definição
    os.system("Xvfb :99 -screen 0 1280x720x24 &")
    os.environ["DISPLAY"] = ":99"
    time.sleep(3) 

    # 5. FFmpeg captura a tela virtual :99.0 completa e limpa (sem mouse)
    ffmpeg_cmd = [
        "ffmpeg", "-f", "pulse", "-i", "auto_null.monitor",
        "-f", "x11grab", "-draw_mouse", "0", "-video_size", "1280x720", "-i", ":99.0",
        "-c:v", "libx264", "-preset", "ultrafast", "-profile:v", "baseline", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-g", "60", "-hls_time", "2", 
        "-hls_list_size", "5", "-hls_flags", "delete_segments", 
        "stream/live.m3u8"
    ]
    print("FFmpeg iniciando gravacao em alta definicao...")
    processo_ffmpeg = subprocess.Popen(ffmpeg_cmd)

    # Tenta ler o link que o Serveo gerou dentro do arquivo temporário
    link_serveo = "https://serveo.net"
    try:
        with open("tunnel.log", "r") as f:
            log_content = f.read()
            for line in log_content.split("\n"):
                if "Forwarding HTTP traffic from" in line:
                    link_serveo = line.split("from")[-1].strip()
    except:
        pass

    # === IMPRIME O SEU LINK ATUALIZADO GIGANTE EM DESTAQUE NO FIM DO LOG ===
    print("\n==========================================================")
    print("========= SEU LINK DE TRANSMISSÃO EM TELA CHEIA =========")
    print(f"{link_serveo}/live.m3u8")
    print("==========================================================\n")

    # 6. Inicializa o navegador focado
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        print("Ligando navegador no MODO QUIOSQUE SEM ABAS...")
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
            time.sleep(12) 
            
            print("Preparando o gatilho de tela cheia por clique legitimado...")
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
            
            page.mouse.move(100, 100)
            time.sleep(0.5)
            page.mouse.move(640, 360)
            time.sleep(0.5)
            
            page.mouse.click(640, 360)
            print("Clique de ativacao executado.")
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
                        print("Troca de video ou perda de foco detectada. Reaplicando clique...")
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
                        page.mouse.move(600, 300)
                        time.sleep(0.2)
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
