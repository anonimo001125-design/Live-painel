const express = require('express');
const puppeteer = require('puppeteer');
const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');

const app = express();
const PORT = process.env.PORT || 3000;
const STREAM_DIR = path.join(__dirname, 'public/stream');

if (!fs.existsSync(STREAM_DIR)){
    fs.mkdirSync(STREAM_DIR, { recursive: true });
}

app.use('/stream', express.static(STREAM_DIR));

// Rota raiz para testar no navegador se o servidor está online
app.get('/', (req, res) => {
    res.send('Servidor de Restream está Online! O link HLS fica em /stream/live.m3u8');
});

async function iniciarTransmissao() {
    console.log("Iniciando Chromium nativo no ambiente virtual...");
    
    let browser;
    try {
        browser = await puppeteer.launch({
            headless: "new",
            executablePath: '/usr/bin/chromium', // Caminho correto do Chromium no Debian/Ubuntu
            args: [
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-dev-shm-usage', // Corrige falhas de falta de memória RAM no Docker
                '--disable-gpu',
                '--display=:99.0',         // Conecta diretamente na tela virtual Xvfb
                '--autoplay-policy=no-user-gesture-required' // Força o vídeo do site a dar Play sozinho
            ]
        });

        const page = await browser.newPage();
        
        // MUDANÇA OBRIGATÓRIA: Altere para o site que você quer capturar
        const urlAlvo = 'https://ais-pre-czbrtxxjttcqeqhdn3kw3n-102718744012.us-east5.run.app/watch'; 
        
        console.log(`Navegando até a página de transmissão: ${urlAlvo}`);
        await page.goto(urlAlvo, { waitUntil: 'domcontentloaded', timeout: 60000 }); // Troca para carregar mais rápido
        await page.setViewport({ width: 1280, height: 720 });

        console.log("Iniciando codificação de vídeo e áudio com FFmpeg...");

        // Argumentos do FFmpeg otimizados para não travarem por falta de hardware físico
        const ffmpegArgs = [
            '-f', 'x11grab',
            '-video_size', '1280x720',
            '-i', ':99.0',               // Captura a tela virtual gerada pelo Xvfb
            '-f', 'lavfi', '-i', 'anullsrc=channel_layout=stereo:sample_rate=44100', // Gera áudio silencioso virtual caso o site não envie áudio
            '-c:v', 'libx264',
            '-preset', 'ultrafast',       // Minimiza o uso de CPU para planos gratuitos
            '-b:v', '600k',              // Bitrate reduzido para evitar gargalos na Render
            '-maxrate', '800k',
            '-bufsize', '1200k',
            '-pix_fmt', 'yuv420p',
            '-g', '50',
            '-c:a', 'aac',
            '-shortest',                  // Sincroniza término dos canais de mídia
            '-f', 'hls',
            '-hls_time', '4',
            '-hls_list_size', '3',        // Reduzido para economizar espaço em disco
            '-hls_flags', 'delete_segments',
            path.join(STREAM_DIR, 'live.m3u8')
        ];

        const ffmpegProcess = spawn('ffmpeg', ffmpegArgs);

        ffmpegProcess.stderr.on('data', (data) => {
            // Mostra os logs do FFmpeg no console da Render para sabermos se ele está capturando frames
            console.log(`[FFmpeg]: ${data.toString().trim()}`);
        });

        ffmpegProcess.on('close', async (code) => {
            console.log(`FFmpeg parou (Código: ${code}). Reiniciando processo...`);
            try { await browser.close(); } catch(e) {}
            setTimeout(iniciarTransmissao, 5000);
        });

    } catch (error) {
        console.error("Erro no fluxo do Restream:", error);
        if (browser) { try { await browser.close(); } catch(e) {} }
        setTimeout(iniciarTransmissao, 10000);
    }
}

app.listen(PORT, () => {
    console.log(`Servidor HTTP iniciado na porta ${PORT}`);
    iniciarTransmissao();
});
