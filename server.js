const express = require('express');
const puppeteer = require('puppeteer');
const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');

const app = express();
const PORT = process.env.PORT || 3000;
const STREAM_DIR = path.join(__dirname, 'public/stream');

// Garante que a pasta onde o streaming HLS será salvo exista em disco [2]
if (!fs.existsSync(STREAM_DIR)){
    fs.mkdirSync(STREAM_DIR, { recursive: true });
}

// Serve publicamente os arquivos .m3u8 e os fragmentos de vídeo .ts [2]
app.use('/stream', express.static(STREAM_DIR));

async function iniciarTransmissao() {
    console.log("Iniciando navegador virtual dentro do Docker...");
    
    let browser;
    try {
        // Inicializa o Puppeteer configurado para a tela virtual (:99.0) criada no Dockerfile
        browser = await puppeteer.launch({
            headless: "new",
            args: [
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-dev-shm-usage', // Evita travamentos por falta de memória compartilhada no container
                '--disable-gpu',
                '--display=:99.0'          // Aponta para o display virtual do Xvfb
            ]
        });

        const page = await browser.newPage();
        
        // RECOMENDAÇÃO: Substitua pela URL do site que você deseja capturar
        const urlAlvo = 'https://ais-pre-czbrtxxjttcqeqhdn3kw3n-102718744012.us-east5.run.app/watch'; 
        
        console.log(`Navegando até: ${urlAlvo}`);
        await page.goto(urlAlvo, { waitUntil: 'networkidle2', timeout: 60000 });
        
        // Define a resolução exata da captura de tela (720p) [2]
        await page.setViewport({ width: 1280, height: 720 });

        console.log("Iniciando processo do FFmpeg para geração do link HLS (.m3u8)...");

        // Argumentos do FFmpeg para capturar a tela virtual Linux e converter em streaming [2]
        const ffmpegArgs = [
            '-f', 'x11grab',             // Captura a interface gráfica do servidor Linux [2]
            '-video_size', '1280x720',    // Resolução da captura [2]
            '-i', ':99.0',               // ID da tela virtual configurada no Dockerfile [2]
            '-c:v', 'libx264',           // Codec de vídeo universal H.264 [2]
            '-preset', 'ultrafast',       // Carregamento mais rápido possível para poupar a CPU da Render
            '-b:v', '800k',              // Taxa de bits estável e leve para ambientes de nuvem [2]
            '-maxrate', '1000k',
            '-bufsize', '2000k',
            '-g', '60',                  // Cria um Keyframe a cada 2 segundos (essencial para HLS)
            '-f', 'hls',                 // Formato de saída HTTP Live Streaming [2]
            '-hls_time', '4',            // Duração de cada segmento .ts em segundos [2]
            '-hls_list_size', '5',       // Mantém apenas os últimos 5 segmentos na lista (evita lotar o disco) [2]
            '-hls_flags', 'delete_segments', // Apaga automaticamente os arquivos antigos do servidor [2]
            path.join(STREAM_DIR, 'live.m3u8') // Arquivo final gerado [2]
        ];

        const ffmpegProcess = spawn('ffmpeg', ffmpegArgs);

        // Captura mensagens de erro e logs de status vindos do FFmpeg
        ffmpegProcess.stderr.on('data', (data) => {
            console.log(`[FFmpeg]: ${data.toString().trim()}`);
        });

        ffmpegProcess.on('close', async (code) => {
            console.log(`FFmpeg foi encerrado (Código: ${code}). Reiniciando processo...`);
            try { await browser.close(); } catch(e) {}
            setTimeout(iniciarTransmissao, 5000); // Tenta reconectar e recomeçar após 5 segundos [2]
        });

    } catch (error) {
        console.error("Erro crítico na execução do Restream:", error);
        if (browser) { try { await browser.close(); } catch(e) {} }
        setTimeout(iniciarTransmissao, 10000); // Em caso de falha de rede, aguarda 10 segundos e tenta novamente
    }
}

// Inicia o servidor HTTP
app.listen(PORT, () => {
    console.log(`Servidor Web ativo na porta ${PORT}`);
    console.log(`Seu link m3u8 final será gerado em: http://localhost:${PORT}/stream/live.m3u8`);
    iniciarTransmissao();
});
