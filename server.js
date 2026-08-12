const express = require('express');
const { launch, getStream } = require('puppeteer-stream');
const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');

const app = express();
const PORT = process.env.PORT || 8080;

// Permite CORS para rodar em players de IPTV/VLC externos
app.use((req, res, next) => {
    res.header('Access-Control-Allow-Origin', '*');
    next();
});

// Serve os arquivos do streaming (.m3u8 e .ts) na web
app.use(express.static(path.join(__dirname, 'stream')));

async function iniciarTransmissao() {
    console.log("Inicializando navegador Duck/Chromium de forma nativa...");
    
    const browser = await launch({
        headless: "new",
        args: [
            '--no-sandbox',
            '--disable-dev-shm-usage',
            '--autoplay-policy=no-user-gesture-required'
        ]
    });

    const page = await browser.newPage();
    await page.setViewport({ width: 1280, height: 720 });

    // URL DO SEU SITE: Altere o link abaixo para a sua página real
    const urlAlvo = "https://ais-pre-czbrtxxjttcqeqhdn3kw3n-102718744012.us-east5.run.app/watch";
    console.log(`Acessando a página: ${urlAlvo}`);
    await page.goto(urlAlvo, { waitUntil: 'networkidle2' });

    // Aguarda o player carregar
    await new Promise(resolve => setTimeout(resolve, 5000));

    console.log("Capturando fluxo interno de áudio e vídeo...");
    const stream = await getStream(page, { audio: true, video: true });

    // Comando FFmpeg configurado para receber o fluxo direto do navegador
    const ffmpegCmd = [
        '-i', '-', // Recebe a entrada diretamente do stream do Puppeteer
        '-c:v', 'libx264', '-profile:v', 'baseline', '-pix_fmt', 'yuv420p',
        '-c:a', 'aac', '-b:a', '128k', '-ar', '44100',
        '-g', '60', '-hls_time', '2', '-hls_list_size', '5',
        '-hls_flags', 'delete_segments',
        path.join(__dirname, 'stream', 'live.m3u8')
    ];

    const ffmpegProcess = spawn('ffmpeg', ffmpegCmd);

    // Conecta o fluxo do navegador na entrada do FFmpeg
    stream.pipe(ffmpegProcess.stdin);

    ffmpegProcess.stderr.on('data', (data) => {
        // Log do FFmpeg caso queira monitorar no painel
        console.log(`FFmpeg: ${data}`);
    });

    ffmpegProcess.on('close', () => {
        console.log("FFmpeg encerrado. Reiniciando transmissão...");
        browser.close();
        iniciarTransmissao();
    });
}

app.listen(PORT, () => {
    console.log(`Servidor Web ativo na porta ${PORT}`);
    iniciarTransmissao();
});
