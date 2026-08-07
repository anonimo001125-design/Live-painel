const express = require('express');
const puppeteer = require('puppeteer');
const { exec } = require('child_process');
const fs = require('fs');
const app = express();

const URL_ALVO = "https://ais-pre-czbrtxxjttcqeqhdn3kw3n-102718744012.us-east5.run.app/watch";

if (!fs.existsSync('./public')) { fs.mkdirSync('./public'); }

async function iniciarNavegadorEStream() {
    console.log("Iniciando navegador camuflado contra tela preta...");
    try {
        const browser = await puppeteer.launch({
            headless: "new",
            args: [
                '--no-sandbox', 
                '--disable-setuid-sandbox',
                '--disable-blink-features=AutomationControlled', // Esconde que é um robô
                '--disable-gpu', // Desativa aceleração de hardware contra tela preta
                '--autoplay-policy=no-user-gesture-required' // Força o som a tocar sozinho
            ]
        });
        const page = await browser.newPage();
        
        // Define o tamanho da tela do robô
        await page.setViewport({ width: 1280, height: 720 });
        
        // Abre o site enganando o sistema de segurança
        await page.setUserAgent('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36');
        await page.goto(URL_ALVO, { waitUntil: 'networkidle2' });
        
        // Clica na tela para garantir o som e tirar avisos
        try {
            await page.click('body');
            console.log("Robô interagiu com a página para ativar áudio e vídeo.");
        } catch(e) {}

        await new Promise(resolve => setTimeout(resolve, 5000));

        // Captura a tela e o ÁUDIO interno da máquina virtual (via pulse)
        console.log("Ligando o conversor FFmpeg com áudio e vídeo...");
        const comando = `Xvfb :99 -screen 0 1280x720x16 & ffmpeg -re -f x11grab -s 1280x720 -i :99 -f pulse -i default -c:v libx264 -preset veryfast -pix_fmt yuv420p -c:a aac -b:a 128k -f hls -hls_time 4 -hls_list_size 5 -hls_flags delete_segments ./public/live.m3u8`;
        
        exec(comando, (err) => {
            if (err) console.error("Erro no FFmpeg:", err);
        });

    } catch (erro) {
        console.error("Erro na captura:", erro);
    }
}

iniciarNavegadorEStream();

app.use(express.static('public'));
app.get('/', (req, res) => { res.send('Servidor de Transmissão 24h Corrigido!'); });

app.listen(process.env.PORT || 3000, () => {
    console.log("Servidor online na porta 3000");
});
