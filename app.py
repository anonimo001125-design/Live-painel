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

    # 4. Configura a tela virtual
    os.system("Xvfb :99 -screen 0 1280x720x24 &")
    os.environ["DISPLAY"] = ":99"
    time.sleep(3) 

    # 5. FFmpeg captura a tela virtual :99.0 limpa (sem mouse)
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
            time.sleep(12) # Tempo para o player carregar completo
            
            # Clique inicial para dar o foco e destravar o som
            page.mouse.click(640, 360)
            time.sleep(1)
            
            # === DESTRUIDOR DE MENUS E ABAS POR FORÇA BRUTA ===
            # Esse script em JavaScript roda na página principal e em todas as internas.
            # Ele localiza o player de vídeo e SIMPLESMENTE DELETA tudo o que está em volta dele na tela.
            print("Executando a limpeza de elementos visuais do site...")
            page.evaluate("""
                // Move o player de vídeo para cobrir 100% da janela visível por cima de tudo
                const videoEl = document.querySelector('video');
                if (videoEl) {
                    videoEl.style.setProperty('position', 'fixed', 'important');
                    videoEl.style.setProperty('top', '0', 'important');
                    videoEl.style.setProperty('left', '0', 'important');
                    videoEl.style.setProperty('width', '100vw', 'important');
                    videoEl.style.setProperty('height', '100vh', 'important');
                    videoEl.style.setProperty('z-index', '999999', 'important');
                }
                
                // Varre e oculta os cabeçalhos comuns que costumam ser as abas do site
                const headers = document.querySelectorAll('header, nav, .navbar, .topbar, #header, .header, .aba, .menu');
                headers.forEach(el => el.style.setProperty('display', 'none', 'important'));
            """)
            
            # Aplica a mesma destruição de menus dentro de qualquer janela cega (iframe) que o site use
            for frame in page.frames:
                try:
                    frame.evaluate("""
                        const innerVideo = document.querySelector('video');
                        if (innerVideo) {
                            innerVideo.style.setProperty('position', 'fixed', 'important');
                            innerVideo.style.setProperty('top', '0', 'important');
                            innerVideo.style.setProperty('left', '0', 'important');
                            innerVideo.style.setProperty('width', '100vw', 'important');
                            innerVideo.style.setProperty('height', '100vh', 'important');
                            innerVideo.style.setProperty('z-index', '999999', 'important');
                        }
                        const innerHeaders = document.querySelectorAll('header, nav, .navbar, .topbar, #header, .header, .aba, .menu');
                        innerHeaders.forEach(el => el.style.setProperty('display', 'none', 'important'));
                    """)
                except:
                    pass
            
            print("Limpeza concluída. Forçando cliques de play...")
            time.sleep(2)
            page.mouse.click(640, 360)
            
        except Exception as e:
            print(f"Aviso inicial: {e}")

        # === MONITOR DE MANUTENÇÃO DA LIMPEZA (Para troca de episódios) ===
        print("Vigia de troca de videos ativo...")
        try:
            while True:
                time.sleep(5) # Verifica a cada 5 segundos se o site mudou de vídeo
                try:
                    # Se o site mudar de vídeo e os menus voltarem, o vigia apaga tudo de novo na hora
                    page.evaluate("""
                        const videoEl = document.querySelector('video');
                        if (videoEl && videoEl.style.position !== 'fixed') {
                            videoEl.style.setProperty('position', 'fixed', 'important');
                            videoEl.style.setProperty('top', '0', 'important');
                            videoEl.style.setProperty('left', '0', 'important');
                            videoEl.style.setProperty('width', '100vw', 'important');
                            videoEl.style.setProperty('height', '100vh', 'important');
                            videoEl.style.setProperty('z-index', '999999', 'important');
                            
                            const headers = document.querySelectorAll('header, nav, .navbar, .topbar, #header, .header, .aba, .menu');
                            headers.forEach(el => el.style.setProperty('display', 'none', 'important'));
                        }
                    """)
                    
                    for frame in page.frames:
                        try:
                            frame.evaluate("""
                                const innerVideo = document.querySelector('video');
                                if (innerVideo && innerVideo.style.position !== 'fixed') {
                                    innerVideo.style.setProperty('position', 'fixed', 'important');
                                    innerVideo.style.setProperty('top', '0', 'important');
                                    innerVideo.style.setProperty('left', '0', 'important');
                                    innerVideo.style.setProperty('width', '100vw', 'important');
                                    innerVideo.style.setProperty('height', '100vh', 'important');
                                    innerVideo.style.setProperty('z-index', '999999', 'important');
                                    
                                    const innerHeaders = document.querySelectorAll('header, nav, .navbar, .topbar, #header, .header, .aba, .menu');
                                    innerHeaders.forEach(el => el.style.setProperty('display', 'none', 'important'));
                                }
                            """)
                        except:
                            pass
                            
                    page.mouse.click(640, 360)
                except:
                    pass
        except KeyboardInterrupt:
            processo_ffmpeg.terminate()
            browser.close()

if __name__ == "__main__":
    iniciar()
