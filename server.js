const express = require('express');
const puppeteer = require('puppeteer');
const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');

const app = express();
const PORT = process.env.PORT || 3000;
const STREAM_DIR = path.join(__dirname, 'public/stream');

if (!fs.existsSync(STREAM_DIR)) fs.mkdirSync(STREAM_DIR, { recursive: true });
app.use('/stream', express.static(STREAM_DIR));
app.get('/', (req, res) => res.send('Captura de Tela Ativa!'));

async function iniciarTransmissao() {
    console.log("Abrindo navegador virtual...");
    let browser;
    
    try {
        browser = await puppeteer.launch({
            headless: "new",
            // Usa o Chrome ultra-estável que já vem embutido na imagem do Docker
            executablePath: process.env.PUPPETEER_EXECUTABLE_PATH, 
            args: [
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-dev-shm-usage',
                '--display=:99.0', // Joga o navegador dentro do monitor virtual
                '--autoplay-policy=no-user-gesture-required',
                '--disable-gpu' // Força renderizar por processador para evitar tela preta
            ]
        });

        const page = await browser.newPage();
        
        // ⚠️ ESCREVA A URL DA PÁGINA DO SEU VÍDEO AQUI
        const urlAlvo = 'https://ais-pre-czbrtxxjttcqeqhdn3kw3n-102718744012.us-east5.run.app/watch'; 
        
        console.log(`Carregando página com logos: ${urlAlvo}`);
        await page.goto(urlAlvo, { waitUntil: 'networkidle2', timeout: 60000 });
        await page.setViewport({ width: 1280, height: 720 });

        // Espera 5 segundos para a página carregar anúncios, logos e o player estabilizar
        await new Promise(resolve => setTimeout(resolve, 5000));

        console.log("Iniciando gravação total da tela...");

        const ffmpegArgs = [
            '-f', 'x11grab',
            '-video_size', '1280x720',
            '-i', ':99.0', // Captura tudo o que está aparecendo na tela virtual
            '-f', 'pulse',
            '-i', 'default', // Captura todo o som do sistema virtual
            '-c:v', 'libx264',
            '-preset', 'ultrafast', // Configuração mais leve para não travar o servidor
            '-b:v', '600k',
            '-maxrate', '800k',
            '-bufsize', '1200k',
            '-pix_fmt', 'yuv420p',
            '-g', '50',
            '-c:a', 'aac',
            '-b:a', '96k',
            '-f', 'hls',
            '-hls_time', '4',
            '-hls_list_size', '3',
            '-hls_flags', 'delete_segments',
            path.join(STREAM_DIR, 'live.m3u8')
        ];

        const ffmpegProcess = spawn('ffmpeg', ffmpegArgs);

        ffmpegProcess.stderr.on('data', (data) => {
            if (data.toString().includes('frame=')) {
                console.log('[GRAVAÇÃO ATIVA] Capturando tela, áudio e logos com sucesso!');
            }
        });

        ffmpegProcess.on('close', async () => {
            console.log("FFmpeg fechado. Reiniciando...");
            try { await browser.close(); } catch(e) {}
            setTimeout(iniciarTransmissao, 5000);
        });

    } catch (error) {
        console.error("Erro na captura:", error);
        if (browser) try { await browser.close(); } catch(e) {}
        setTimeout(iniciarTransmissao, 10000);
    }
}

app.listen(PORT, () => {
    console.log(`Servidor rodando na porta ${PORT}`);
    iniciarTransmissao();
});
