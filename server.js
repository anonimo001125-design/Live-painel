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
    res.send('Servidor de Restream ativo! Link em: /stream/live.m3u8');
});

async function iniciarTransmissao() {
    console.log("Iniciando Chromium no display virtual...");
    
    let browser;
    try {
        browser = await puppeteer.launch({
            headless: "new",
            executablePath: '/usr/bin/chromium',
            args: [
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-dev-shm-usage',
                '--disable-gpu',
                '--display=:99.0', // Conecta na tela virtual Xvfb
                '--autoplay-policy=no-user-gesture-required' // Tenta forçar o autoplay do som
            ]
        });

        const page = await browser.newPage();
        
        // OBRIGATÓRIO: Coloque a URL do site de vídeo aqui
        const urlAlvo = 'https://ais-pre-czbrtxxjttcqeqhdn3kw3n-102718744012.us-east5.run.app/watch'; 
        
        console.log(`Carregando a página: ${urlAlvo}`);
        // Aguarda a página carregar completamente os elementos visuais
        await page.goto(urlAlvo, { waitUntil: 'networkidle2', timeout: 60000 });
        
        // Define a resolução da janela do navegador
        await page.setViewport({ width: 1280, height: 720 });

        // --- SOLUÇÃO PARA TELA PRETA (AUTOPLAY / CLIQUE) ---
        console.log("Aguardando 5 segundos para estabilização da página...");
        await new Promise(resolve => setTimeout(resolve, 5000));

        // Se o site tiver um botão de "Play", descomente as linhas abaixo e coloque a classe/ID dele:
        // try {
        //     await page.click('.botao-play-do-site'); // Altere para o seletor real do botão
        //     console.log("Botão de Play clicado via automação!");
        // } catch(e) {
        //     console.log("Não foi necessário clicar em botão de play externo.");
        // }

        // Garante que o volume da página esteja no máximo via execução de script na página
        await page.evaluate(() => {
            const videos = document.querySelectorAll('video');
            videos.forEach(v => {
                v.muted = false;
                v.volume = 1.0;
                v.play().catch(err => console.log("Erro ao dar play automático no elemento:", err));
            });
        });

        console.log("Iniciando FFmpeg para capturar a imagem e o som...");

        // --- SOLUÇÃO PARA CAPTURA DE ÁUDIO E VÍDEO REAL ---
        const ffmpegArgs = [
            '-f', 'x11grab',
            '-video_size', '1280x720',
            '-i', ':99.0', // Captura a imagem da tela virtual do Chromium
            
            // Procura o áudio interno gerado pelo Chromium (gerado através do ALSA virtual no Docker)
            '-f', 'alsa', '-i', 'default', 
            
            '-c:v', 'libx264',
            '-preset', 'ultrafast',
            '-b:v', '700k', // Bitrate equilibrado para a Render Free
            '-maxrate', '900k',
            '-bufsize', '1400k',
            '-pix_fmt', 'yuv420p',
            '-g', '50',
            '-c:a', 'aac', // Codifica o áudio capturado em formato AAC
            '-b:a', '128k',
            '-f', 'hls',
            '-hls_time', '4',
            '-hls_list_size', '3',
            '-hls_flags', 'delete_segments',
            path.join(STREAM_DIR, 'live.m3u8')
        ];

        const ffmpegProcess = spawn('ffmpeg', ffmpegArgs);

        ffmpegProcess.stderr.on('data', (data) => {
            const log = data.toString();
            // Filtragem simples para monitorar se frames estão sendo processados
            if (log.includes('frame=')) {
                console.log(`[FFmpeg Status]: ${log.trim().substring(0, 60)}`);
            }
        });

        ffmpegProcess.on('close', async (code) => {
            console.log(`FFmpeg fechado (Código: ${code}). Reiniciando restream...`);
            try { await browser.close(); } catch(e) {}
            setTimeout(iniciarTransmissao, 5000);
        });

    } catch (error) {
        console.error("Falha no Restream:", error);
        if (browser) { try { await browser.close(); } catch(e) {} }
        setTimeout(iniciarTransmissao, 10000);
    }
}

app.listen(PORT, () => {
    console.log(`Servidor rodando na porta ${PORT}`);
    iniciarTransmissao();
});
