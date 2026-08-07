const express = require('express');
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
    res.send('Servidor de Restream Direto Ativo! Seu link HLS está em /stream/live.m3u8');
});

function iniciarTransmissao() {
    // RECOMENDAÇÃO CRÍTICA: Substitua pelo link real da página ou da live que quer retransmitir
    const urlAlvo = 'https://ais-pre-czbrtxxjttcqeqhdn3kw3n-102718744012.us-east5.run.app/watch'; 

    console.log(`Extraindo fluxo direto de vídeo de: ${urlAlvo}...`);

    // Executa o yt-dlp para obter a URL direta da mídia (ignora a interface do site)
    const ytdlp = spawn('yt-dlp', ['-g', '-f', 'best', urlAlvo]);

    let urlDiretaMidia = '';

    ytdlp.stdout.on('data', (data) => {
        urlDiretaMidia += data.toString().trim();
    });

    ytdlp.on('close', (code) => {
        if (code !== 0 || !urlDiretaMidia) {
            console.error("Não foi possível extrair o fluxo do site. Tentando novamente em 10 segundos...");
            setTimeout(iniciarTransmissao, 10000);
            return;
        }

        console.log("Fluxo de mídia encontrado com sucesso!");
        console.log("Iniciando FFmpeg direto na fonte (Consumo de RAM mínimo)...");

        // O FFmpeg agora lê direto o arquivo de rede do vídeo, copiando o codec sem processar tela gráfica
        const ffmpegArgs = [
            '-re',                           // Lê a entrada em tempo real
            '-i', urlDiretaMidia,            // URL direta do vídeo extraído do site
            '-c:v', 'libx264',               // Garante compatibilidade universal do codec de vídeo
            '-preset', 'ultrafast',
            '-b:v', '600k',                  // Bitrate super leve e estável para a Render Free
            '-maxrate', '800k',
            '-bufsize', '1200k',
            '-pix_fmt', 'yuv420p',
            '-g', '50',
            '-c:a', 'aac',                   // Garante codec de áudio correto
            '-b:a', '96k',
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
                console.log(`[Streaming OK] Transmitindo frames reais: ${log.trim().substring(0, 50)}`);
            }
        });

        ffmpegProcess.on('close', (ffmpegCode) => {
            console.log(`FFmpeg encerrado (Código: ${ffmpegCode}). Reiniciando processo de extração...`);
            setTimeout(iniciarTransmissao, 5000);
        });
    });
}

app.listen(PORT, () => {
    console.log(`Servidor HTTP iniciado na porta ${PORT}`);
    iniciarTransmissao();
});
