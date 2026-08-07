const puppeteer = require('puppeteer');
const { spawn } = require('child_process');

async function startStream() {
  const browser = await puppeteer.launch({ args: ['--no-sandbox', '--use-fake-ui-for-media-stream'] });
  const page = await browser.newPage();
  await page.goto('https://ais-pre-czbrtxxjttcqeqhdn3kw3n-102718744012.us-east5.run.app/watch');

  // O FFmpeg recebe a captura e transforma em HLS (.m3u8)
  const ffmpeg = spawn('ffmpeg', [
    '-f', 'gdigrab', // Ou o equivalente para capturar o display virtual no Linux
    '-i', ':99',     // Display do servidor virtual Xvfb
    '-c:v', 'libx264',
    '-pix_fmt', 'yuv420p',
    '-f', 'hls',
    '-hls_time', '4',
    '-hls_list_size', '5',
    './output/stream.m3u8' // O link gerado
  ]);
}
startStream();
