async def abrir_navegador():

    print("Abrindo Chromium...")

    browser = await launch(
        headless=False,

        # Usa o Chromium instalado no GitHub Actions
        executablePath="/usr/bin/chromium",

        # Remove somente a barra:
        # "Chrome is being controlled by automated test software"
        ignoreDefaultArgs=[
            "--enable-automation"
        ],

        args=[
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",

            # Permite autoplay quando o próprio site solicitar
            "--autoplay-policy=no-user-gesture-required",

            # Modo TV
            "--kiosk",
            "--start-fullscreen",

            # Resolução
            "--window-size=1280,720",

            # Inicialização limpa
            "--no-first-run",
            "--no-default-browser-check"
        ]
    )

    page = await browser.newPage()

    await page.setViewport({
        "width": 1280,
        "height": 720
    })

    url_alvo = (
        "https://ais-pre-czbrtxxjttcqeqhdn3kw3n-102718744012"
        ".us-east5.run.app/watch"
    )

    print("")
    print("==========================================================")
    print("ABRINDO PAINEL DA WEB TV")
    print("==========================================================")
    print(url_alvo)
    print("")

    try:

        await page.goto(
            url_alvo,
            {
                "waitUntil": "domcontentloaded",
                "timeout": 120000
            }
        )

        print("Painel carregado com sucesso.")

    except Exception as erro:

        print("Aviso ao abrir o painel:")
        print(erro)

    print("Aguardando o painel estabilizar...")

    # Dá tempo para o painel carregar os componentes,
    # mas NÃO interfere nos vídeos.
    await asyncio.sleep(10)

    print("")
    print("==========================================================")
    print("WEB TV ONLINE")
    print("Chromium em modo quiosque.")
    print("O painel controla os vídeos normalmente.")
    print("==========================================================")
    print("")

    # ========================================================
    # IMPORTANTE:
    # Não fazemos mais:
    #
    # video.play()
    # video.muted = false
    # monitoramento de video.paused
    #
    # O próprio painel controla seus vídeos.
    # ========================================================

    while True:

        await asyncio.sleep(30)

        try:

            # Apenas verifica se a página continua aberta.
            # Não toca nem modifica os vídeos.

            titulo = await page.title()

            print(
                f"Painel ativo: {titulo}"
            )

        except Exception as erro:

            print(
                "Aviso monitorando página:",
                erro
            )
