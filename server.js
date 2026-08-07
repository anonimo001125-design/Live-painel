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

app.get('/', (req, res) => {
    res.send('Servidor ativo.');
});

async function iniciarTransmissao() {
    console.log("Iniciando Chromium com emulação de software...");
    
    let browser;
    try {
        browser = await puppeteer.launch({
            headless: "new",
            executablePath: '/usr/bin/chromium',
            args: [
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-dev-shm-usage',
                '--display=:99.0',
                '--autoplay-policy=no-user-gesture-required',
                
                // --- FLAGS CRÍTICAS PARA ACABAR COM A TELA PRETA ---
                '--disable-gpu',                     // Desativa uso da GPU física
                '--disable-software-rasterizer',    // Força uso do processador
                '--disable-gpu-sandbox',            // Ignora isolamento de hardware
                '--audio-buffer-size=4096'          // Melhora estabilidade do buffer de som
            ]
        });

        const page = await browser.newPage();
        
        // MUDANÇA OBRIGATÓRIA: Insira a URL do seu vídeo abaixo
        const urlAlvo = 'https://ais-pre-czbrtxxjttcqeqhdn3kw3n-102718744012.us-east5.run.app/watch'; 
        
        console.log(`Carregando: ${urlAlvo}`);
        await page.goto(urlAlvo, { waitUntil: 'networkidle2', timeout: 60000 });
        await page.setViewport({ width: 1280, height: 720 });

        // Aguarda carregamento total dos players internos do site
        await new Promise(resolve => setTimeout(resolve, 8000));

        // Força a ativação de áudio e play de todas as tags de vídeo na página
        await page.evaluate(() => {
            const videoElements = document.querySelectorAll('video');
            videoElements.forEach(video => {
                video.muted = false;
                video.volume = 1.0;
                // Executa um trigger interno de reprodução
                video.play().catch(e => console.log("Play pendente:", e));
            });
        });

        console.log("Iniciando FFmpeg via PulseAudio (Som) e X11 (Imagem)...");

        const ffmpegArgs = [
            '-f', 'x11grab',
            '-video_size', '1280x720',
            '-i', ':99.0',                // Captura a tela virtual
            
            '-f', 'pulse',
            '-i', 'default',              // Captura o áudio processado pelo PulseAudio virtual
            
            '-c:v', 'libx264',
            '-preset', 'ultrafast',       // Economiza uso de CPU na Render Free
            '-b:v', '650k',
            '-maxrate', '850k',
            '-bufsize', '1300k',
            '-pix_fmt', 'yuv420p',
            '-g', '50',
            '-c:a', 'aac',
            '-b:a', '128k',
            '-ac', '2',                   // Força saída em Stereo
            '-f', 'hls',
            '-hls_time', '4',
            '-hls_list_size', '3',
            '-hls_flags', 'delete_segments',
            path.join(STREAM_DIR, 'live.m3u8')
        ];

        const ffmpegProcess = spawn('ffmpeg', ffmpegArgs);

        ffmpegProcess.stderr.on('data', (data) => {
            const log = data.toString();
            if (log.includes('frame=')) {
                // Monitora se o vídeo está de fato gerando FPS e bitrate
                console.log(`[Streaming Ativo]: ${log.trim().substring(0, 65)}`);
            }
        });

        ffmpegProcess.on('close', async (code) => {
            console.log(`FFmpeg parou (Código: ${code}). Reiniciando...`);
            try { await browser.close(); } catch(e) {}
            setTimeout(iniciarTransmissao, 5000);
        });

    } catch (error) {
        console.error("Erro no Restream:", error);
        if (browser) { try { await browser.close(); } catch(e) {} }
        setTimeout(iniciarTransmissao, 10000);
    }
}

app.listen(PORT, () => {
    console.log(`Servidor rodando na porta ${PORT}`);
    iniciarTransmissao();
});
