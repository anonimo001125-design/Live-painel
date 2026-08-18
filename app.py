def iniciar_tunel():

    global tunnel_process

    log("")
    log("[6] Iniciando túnel público...")
    log("")

    tunnel_process = subprocess.Popen(
        [
            "ssh",
            "-o", "StrictHostKeyChecking=no",
            "-o", "ServerAliveInterval=30",
            "-o", "ServerAliveCountMax=3",
            "-o", "ExitOnForwardFailure=yes",
            "-R", f"80:localhost:{HTTP_PORT}",
            "nokey@localhost.run"
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )

    inicio = time.time()
    link_encontrado = False

    while time.time() - inicio < 60:

        if tunnel_process.poll() is not None:

            log("")
            log("[ERRO] O túnel encerrou.")
            log(
                "Código:",
                tunnel_process.returncode
            )

            break

        linha = tunnel_process.stdout.readline()

        if not linha:
            time.sleep(0.2)
            continue

        linha = linha.strip()

        log("[TUNEL]", linha)

        # Procura qualquer endereço HTTPS
        if "https://" in linha:

            partes = linha.split()

            for parte in partes:

                if parte.startswith("https://"):

                    url = parte.strip(
                        ".,;()[]{}<>\"'"
                    )

                    # Remove possíveis caracteres extras
                    url = url.rstrip("/")

                    link_encontrado = True

                    log("")
                    log(
                        "=========================================================="
                    )
                    log(
                        "          TRANSMISSÃO AO VIVO"
                    )
                    log(
                        "=========================================================="
                    )
                    log("")
                    log(
                        "LINK DA TRANSMISSÃO:"
                    )
                    log(
                        url
                    )
                    log("")
                    log(
                        "LINK HLS:"
                    )
                    log(
                        url + "/live.m3u8"
                    )
                    log("")
                    log(
                        "=========================================================="
                    )
                    log("")

                    return

    if not link_encontrado:

        log("")
        log(
            "=========================================================="
        )
        log(
            "ERRO: O TÚNEL NÃO FORNECEU UM LINK"
        )
        log(
            "=========================================================="
        )
        log("")
        log(
            "Saída recebida pelo túnel:"
        )

        try:

            while True:

                linha = tunnel_process.stdout.readline()

                if not linha:
                    break

                log(
                    "[TUNEL]",
                    linha.rstrip()
                )

        except Exception:
            pass

        log("")
        log(
            "A transmissão local continua disponível em:"
        )
        log(
            f"http://127.0.0.1:{HTTP_PORT}/live.m3u8"
        )
        log("")
