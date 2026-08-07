import os
import requests
from bs4 import BeautifulSoup

# INSTRUÇÃO: Substitua o link abaixo pela URL real do seu painel de vídeos
URL_DO_PAINEL = "https://ais-pre-czbrtxxjttcqeqhdn3kw3n-102718744012.us-east5.run.app/watch"

def capturar_video():
    try:
        # O robô entra no site do painel
        resposta = requests.get(URL_DO_PAINEL, timeout=10)
        soup = BeautifulSoup(resposta.text, 'html.parser')
        
        # O robô procura pelo link do MP4 atual na página
        tag_video = soup.find('video')
        if tag_video and tag_video.get('src'):
            link_mp4 = tag_video.get('src')
            
            # Se for um link incompleto, transforma em link inteiro
            if not link_mp4.startswith('http'):
                link_mp4 = os.path.dirname(URL_DO_PAINEL) + '/' + link_mp4
                
            print(f"Vídeo encontrado: {link_mp4}")
            
            # Cria o arquivo de playlist M3U apontando diretamente para o MP4 atual
            conteudo_m3u8 = f"#EXTM3U\n#EXTINF:-1,Vídeo ao Vivo\n{link_mp4}\n"
            
            with open("live.m3u8", "w", encoding="utf-8") as f:
                f.write(conteudo_m3u8)
                
    except Exception as e:
        print(f"Erro ao capturar o site: {e}")

if __name__ == "__main__":
    capturar_video()
