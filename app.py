import os
import time
import subprocess
from playwright.sync_api import sync_playwright

def iniciar():
    print("Iniciando tunel de rede...")
    
    # 1. COLOQUE O SEU TOKEN DO NGROK ENTRE AS ASPAS:
    TOKEN_NGROK = "3Hp2YbxQ2bolHAikPRlZgIA4Rtr_71CZKugfEWPTKPS9LXXJk"
    
    from pyngrok import ngrok
    ngrok.set_auth_token(TOKEN_NGROK)
    url_publica = ngrok.connect(8080).public_url
    
    print("\n==========================================================")
    print("========= SEU LINK DE TRANSMISSAO EM TEMPO REAL =========")
    print(f"{url_publica}/live.m3u8")
    print("==========================================================\n")

    with sync_playwright() as p:
        print("Ligando navegador interno com gravador de video...")
        
        # Abre o navegador e grava a tela diretamente por dentro do Playwright (Sem precisar do FFmpeg para a imagem!)
        browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        
        # Ativa a gravação interna de vídeo da própria página na pasta stream
        context = browser.new_context(
            viewport={"width": 1280, "height": 720},
            record_video_dir="stream_raw/"
        )
        page = context.new_page()
        
        # Sua URL alvo recuperada do log do seu erro
        url_alvo = "https://ais-pre-czbrtxxjttcqeqhdn3kw3n-102718744012.us-east5.run.app/watch"
        
        print(f"Acessando o site: {url_alvo}")
        
        try:
            # CORREÇÃO DO TIMEOUT: O timeout=0 faz o robô esperar o tempo que for preciso para o site abrir
            page.goto(url_alvo, wait_until="commit", timeout=0)
            print("Pagina conectada! Aguardando reproducao do conteudo...")
            
            # Deixa o site carregando e transmitindo por 2 horas seguidas (7200 segundos)
            # Você pode aumentar esse número se quiser que a live dure mais tempo
            time.sleep(7200) 
            
        except Exception as e:
            print(f"Aviso durante a execucao: {e}")
        
        # Comando para converter o áudio virtual e juntar com o fluxo
        ffmpeg_cmd = [
            "ffmpeg", "-f", "pulse", "-i", "default",
            "-c:v", "libx264", "-profile:v", "baseline", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k", "-g", "60", "-hls_time", "2", 
            "-hls_list_size", "5", "-hls_flags", "delete_segments", 
            "stream/live.m3u8"
        ]
        subprocess.Popen(ffmpeg_cmd)
        
        print("Servidor ativo na porta 8080...")
        os.makedirs("stream", exist_ok=True)
        os.chdir("stream")
        os.system("python3 -m http.server 8080")

if __name__ == "__main__":
    iniciar()
