const express = require('express');
const puppeteer = require('puppeteer');
const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');

const app = express();
const PORT = process.env.PORT || 3000;
const STREAM_DIR = path.join(__dirname, 'public/stream');

// Garante que a pasta do streaming HLS exista
if (!fs.existsSync(STREAM_DIR)){
    fs.mkdirSync(STREAM_DIR, { recursive: true });
}

// Serve os arquivos .m3u8 e .ts publicamente
app.use('/stream', express.static(STREAM_DIR));

async function iniciarTransmissao() {
    console.log("Iniciando navegador virtual...");
    
    // Abre o navegador em modo headless preparado para Render (Linux)
    const browser = await puppeteer.launch({
        headless: "new",
        args: [
            '--no-sandbox',
            '--disable-setuid-sandbox',
            '--allow-http-screen-capture',
            '--disable-gpu'
        ]
    });

    const page = await browser.newPage();
    
    // Altere para a URL da página web que exibe os vídeos
    const urlAlvo = 'https://ais-pre-czbrtxxjttcqeqhdn3kw3n-102718744012.us-east5.run.app/watch'; 
    await page.goto(urlAlvo, { waitUntil: 'networkidle2' });
    
    // Configura a resolução da tela virtual (Ex: 720p)
    await page.setViewport({ width: 1280, height: 720 });

    console.log("Capturando tela e iniciando FFmpeg...");

    // Comando FFmpeg para capturar a tela do ambiente Linux (X11) e converter para HLS (.m3u8)
    const ffmpegArgs = [
        '-f', 'x11grab',          // Captura o servidor de exibição Linux
        '-video_size', '1280x720',
        '-i', ':99.0',            // Porta padrão do display virtual xvfb
        '-f', 'alsa', '-i', 'hw:0', // Captura o áudio virtual (se configurado)
        '-c:v', 'libx264',        // Codec de vídeo
        '-preset', 'veryfast',
        '-b:v', '1000k',          // Bitrate de vídeo moderado para não estourar limite da Render
        '-c:a', 'aac',            // Codec de áudio
        '-b:a', '1280k',
        '-f', 'hls',              // Formato de saída HTTP Live Streaming
        '-hls_time', '4',         // Tempo de cada fragmento .ts (segundos)
        '-hls_list_size', '5',    // Quantidade de fragmentos salvos na lista
        '-hls_flags', 'delete_segments', // Apaga fragmentos antigos para não lotar o disco
        path.join(STREAM_DIR, 'live.m3u8') // Nome do arquivo gerado
    ];

    const ffmpegProcess = spawn('ffmpeg', ffmpegArgs);

    ffmpegProcess.stderr.on('data', (data) => {
        // Log do status da conversão
        console.log(`[FFmpeg]: ${data}`);
    });

    ffmpegProcess.on('close', (code) => {
        console.log(`FFmpeg encerrado com código: ${code}. Reiniciando...`);
        browser.close();
        setTimeout(iniciarTransmissao, 5000); // Tenta reiniciar em caso de queda
    });
}

app.listen(PORT, () => {
    console.log(`Servidor HTTP rodando na porta ${PORT}`);
    iniciarTransmissao();
});
