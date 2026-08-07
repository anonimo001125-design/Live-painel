const express = require('express');
const puppeteer = require('puppeteer');
const { exec } = require('child_process');
const fs = require('fs');
const app = express();

const URL_ALVO = "https://run.app";

if (!fs.existsSync('./public')) { fs.mkdirSync('./public'); }

async function iniciarNavegadorEStream() {
    console.log("Iniciando navegador invisível para burlar os cookies...");
    try {
        const browser = await puppeteer.launch({
            headless: "new",
            args: ['--no-sandbox', '--disable-setuid-sandbox']
        });
        const page = await browser.newPage();
        
        // Abre o site simulando um acesso real
        await page.goto(URL_ALVO, { waitUntil: 'networkidle2' });
        
        // Clica no botão de permissão de cookies se ele aparecer
        try {
            await page.waitForSelector('button', { timeout: 5000 });
            await page.click('button'); 
            console.log("Cookies aceitos automaticamente pelo robô.");
        } catch(e) {
            console.log("Botão de cookies não apareceu ou já foi ignorado.");
        }

        await new Promise(resolve => setTimeout(resolve, 5000));

        // Captura a tela do navegador virtual e gera o arquivo .m3u8
        console.log("Ligando o conversor FFmpeg 24h...");
        const comando = `Xvfb :99 -screen 0 1280x720x16 & ffmpeg -re -f x11grab -s 1280x720 -i :99 -c:v libx264 -preset veryfast -pix_fmt yuv420p -c:a aac -b:a 128k -f hls -hls_time 4 -hls_list_size 5 -hls_flags delete_segments ./public/live.m3u8`;
        
        exec(comando, (err) => {
            if (err) console.error("Erro no FFmpeg:", err);
        });

    } catch (erro) {
        console.error("Erro ao iniciar captura do site:", erro);
    }
}

iniciarNavegadorEStream();

// Deixa o arquivo .m3u8 público
app.use(express.static('public'));
app.get('/', (req, res) => { res.send('Servidor de Transmissão 24h Ativo!'); });

app.listen(process.env.PORT || 3000, () => {
    console.log("Servidor online na porta 3000");
});
