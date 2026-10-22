"""Extractor de ofertas de trabajo de Computrabajo.

Uso:
    python SCR.py "python" "bogota"
    python SCR.py --headless "analista de datos" "medellin"
    python SCR.py -y --headless "java" "cali"   # Acepta términos programáticamente

Dependencias:
    pip install beautifulsoup4 selenium

El resultado se guarda en un CSV y se registra en computrabajo_scraper.log.

AVISO LEGAL Y ÉTICO:
    Este software se proporciona exclusivamente con fines educativos, de
    investigación y uso personal. Su uso debe respetar los Términos y
    Condiciones de Computrabajo. No está diseñado para extracciones masivas
    ni de alta frecuencia. El autor no se responsabiliza por el mal uso de
    esta herramienta ni por las consecuencias legales derivadas de ello.
"""

from __future__ import annotations

import argparse
import csv
import logging
import os
import random
import re
import ssl
import sys
import time
import urllib3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode, urljoin, urlparse

from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait

# Parches de seguridad para evitar errores de SSL en Windows/Redes corporativas
ssl._create_default_https_context = ssl._create_unverified_context
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_URL = "https://www.computrabajo.com.co"
SEARCH_PATH = "/ofertas-de-trabajo/"
LOG_FILE = "computrabajo_scraper.log"
DEFAULT_TIMEOUT = 15
DEFAULT_MAX_RESULTS = 20
DEFAULT_RETRIES = 2

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# Selectores robustos con múltiples fallbacks
JOB_CARD_SELECTOR = (
    "article.box_offer, article.iO, article[data-id], div.job-card, article"
)

NO_RESULTS_MARKERS = (
    "no encontramos ofertas",
    "no se encontraron ofertas",
    "no hay ofertas",
    "no tenemos ofertas",
    "no encontramos resultados",
    "acceso denegado",
)

CSV_HEADERS = ["Título", "Empresa", "Ubicación", "URL", "Fuente", "Fecha"]

# Selectores de elementos de calificación que contaminan el nombre de la empresa
RATING_SELECTOR = "span.fx_none, [class*='rating'], [class*='score'], [class*='star']"

# Prefijo numérico de calificación (ej: "4,3") que puede quedar en el texto
RATING_PREFIX = re.compile(r"^\d+[.,]\d+\s*")

# ==============================================================================
# AVISO LEGAL Y ÉTICO DE USO
# ==============================================================================
LEGAL_NOTICE = (
    "AVISO LEGAL Y ÉTICO DE USO\n"
    "1. Este software se proporciona exclusivamente con fines educativos, de investigación y uso personal.\n"
    "2. Su uso debe respetar los Términos y Condiciones de Computrabajo:\n"
    "   https://www.computrabajo.com.co/terminos-y-condiciones\n"
    "3. No está diseñado para extracciones masivas, agresivas o de alta frecuencia que sobrecarguen los servidores del sitio.\n"
    "4. Solo se recopila información pública de ofertas de trabajo; no se extrae información personal de terceros.\n"
    "5. El autor no se responsabiliza por el mal uso de esta herramienta, bloqueos de IP o consecuencias legales derivadas.\n"
)

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


# ==============================================================================
# CONFIGURACIÓN DE LOGGING
# ==============================================================================
def setup_logging() -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    try:
        handlers.insert(0, logging.FileHandler(LOG_FILE, encoding="utf-8"))
    except OSError as exc:
        print(
            f"Aviso: no se pudo abrir '{LOG_FILE}' para escritura: {exc}",
            file=sys.stderr,
        )

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=handlers,
        force=True,
    )


# ==============================================================================
# GESTIÓN DEL AVISO LEGAL
# ==============================================================================
def display_legal_notice(auto_accept: bool) -> bool:
    """Muestra el aviso legal y gestiona el consentimiento del usuario.

    Retorna True si el usuario (o la bandera --accept-terms) acepta los términos.
    Deja constancia de la aceptación en el log para fines de auditoría.
    """
    print("=" * 80)
    print(LEGAL_NOTICE)
    print("=" * 80)

    if auto_accept:
        logger.info("Aviso legal aceptado de forma programática mediante --accept-terms.")
        return True

    try:
        answer = input("¿Aceptas los términos y condiciones de uso? (s/n): ").strip().lower()
    except EOFError:
        logger.warning(
            "No se pudo solicitar la aceptación del aviso legal (entorno no interactivo). "
            "Usa la bandera --accept-terms si estás de acuerdo con los términos."
        )
        return False

    accepted = answer in ("s", "si", "sí", "y", "yes")
    if accepted:
        logger.info("Aviso legal aceptado manualmente por el usuario.")
    else:
        logger.info("El usuario rechazó el aviso legal; se cancela la ejecución.")
    return accepted


# ==============================================================================
# UTILIDADES
# ==============================================================================
def clean_text(text: object) -> str:
    """Normaliza espacios y saltos de línea de un texto extraído del HTML."""
    if text is None:
        return ""
    return " ".join(str(text).replace("\u00a0", " ").split())


def build_search_url(keyword: str, location: str = "") -> str:
    """Construye una URL de búsqueda codificando correctamente los parámetros."""
    params = {"q": keyword.strip()}
    if location.strip():
        params["l"] = location.strip()
    return f"{BASE_URL}{SEARCH_PATH}?{urlencode(params)}"


def is_allowed_job_url(url: str) -> bool:
    """Evita abrir o guardar enlaces externos o con esquemas no seguros."""
    parsed = urlparse(url)
    if parsed.scheme != "https":
        return False

    host = (parsed.hostname or "").lower()
    return host == "computrabajo.com.co" or host.endswith(".computrabajo.com.co")


def _absolute_job_url(anchor) -> Optional[str]:
    href = clean_text(anchor.get("href"))
    if not href or href.startswith(("javascript:", "mailto:", "tel:", "#")):
        return None

    absolute = urljoin(f"{BASE_URL}/", href).split("#", 1)[0]
    if not is_allowed_job_url(absolute):
        return None
    return absolute


def runs_without_display() -> bool:
    """Detecta entornos sin interfaz gráfica (Codespaces, CI, servidores).

    En estos entornos Chrome no puede abrir ventanas físicas, por lo que el
    modo headless debe activarse automáticamente para evitar el error
    'session not created: Chrome instance exited'.
    """
    if os.environ.get("CODESPACES") or os.environ.get("CI"):
        return True
    return sys.platform.startswith("linux") and not os.environ.get("DISPLAY")


def runs_in_container() -> bool:
    """Detecta contenedores o root, donde el sandbox de Chrome no es viable."""
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        return True
    if os.environ.get("CODESPACES") or os.environ.get("CI"):
        return True
    return Path("/.dockerenv").exists()


# ==============================================================================
# MODELO DE DATOS
# ==============================================================================
@dataclass
class JobOffer:
    title: str
    company: str
    location: str
    url: str
    source: str = "Computrabajo"
    date_scraped: str = ""

    def __post_init__(self) -> None:
        self.date_scraped = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.title = clean_text(self.title)
        self.company = clean_text(self.company)
        self.location = clean_text(self.location)
        self.url = clean_text(self.url)

    @staticmethod
    def sanitize_csv_cell(value: object) -> str:
        """Neutraliza fórmulas para evitar CSV injection al abrir en Excel."""
        text = "" if value is None else str(value)
        if text.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")):
            return "'" + text
        return text

    def to_csv_row(self) -> list[str]:
        return [
            self.sanitize_csv_cell(self.title),
            self.sanitize_csv_cell(self.company),
            self.sanitize_csv_cell(self.location),
            self.sanitize_csv_cell(self.url),
            self.sanitize_csv_cell(self.source),
            self.sanitize_csv_cell(self.date_scraped),
        ]


# ==============================================================================
# PARSER DE RESULTADOS
# ==============================================================================
def _find_job_anchor(card):
    """Devuelve el enlace principal de una tarjeta de oferta, si es válido."""
    fallback = None

    for anchor in card.find_all("a", href=True):
        absolute = _absolute_job_url(anchor)
        if not absolute:
            continue

        path = urlparse(absolute).path
        if "oferta-de-trabajo-de-" in path:
            return anchor, absolute
        if fallback is None and SEARCH_PATH in path:
            fallback = (anchor, absolute)

    return fallback


def find_job_cards(soup: BeautifulSoup) -> list:
    cards = soup.select(JOB_CARD_SELECTOR)
    if cards:
        return cards

    return [
        article
        for article in soup.find_all("article")
        if _find_job_anchor(article) is not None
    ]


def _first_text(card, selectors: tuple[str, ...]) -> str:
    for selector in selectors:
        element = card.select_one(selector)
        if element is not None:
            text = clean_text(element.get_text(" ", strip=True))
            if text:
                return text
    return ""


def extract_title(card, title_anchor) -> str:
    title = _first_text(
        card,
        ("h2 a.js-o-link", "h2 a", "h2", "h3 a", "h3", "a"),
    )
    if title:
        return title
    return clean_text(title_anchor.get_text(" ", strip=True))


def extract_company(card) -> str:
    company = _first_text(
        card,
        (
            "[offer-grid-article-company-url]",
            "a[href*='/empresas/']",
            "a.company",
            "span.company",
            "[class*='company']",
        ),
    )
    if company:
        return company

    # Fallback para empresas confidenciales: Computrabajo muestra textos como
    # "Importante empresa del sector", a veces precedidos por la calificación
    # del empleador (ej: "4,3"). Se extirpan los elementos de calificación y
    # se limpia cualquier prefijo numérico residual.
    for paragraph in card.select("p.dFlex, p, div"):
        for rating in paragraph.select(RATING_SELECTOR):
            rating.extract()
        text = clean_text(paragraph.get_text(" ", strip=True))
        if text and ("empresa" in text.lower() or "sector" in text.lower()):
            return RATING_PREFIX.sub("", text, count=1).strip()

    return "No especificado"


def extract_location(card) -> str:
    location = _first_text(
        card,
        (
            "p.fs16.fc_base.mt5:not(.dFlex) span.mr10",
            "span.location",
            "div.location",
            "[class*='location']",
            "span.mr10",
        ),
    )
    return location or "No especificado"


def looks_like_no_results(soup: BeautifulSoup) -> bool:
    text = clean_text(soup.get_text(" ", strip=True)).lower()
    return any(marker in text for marker in NO_RESULTS_MARKERS)


def parse_jobs(html: str, max_results: int = DEFAULT_MAX_RESULTS) -> list[JobOffer]:
    """Extrae y deduplica las ofertas de una página de resultados."""
    if max_results <= 0:
        raise ValueError("max_results debe ser mayor que cero")

    soup = BeautifulSoup(html, "html.parser")
    jobs: list[JobOffer] = []
    seen_urls: set[str] = set()

    for card in find_job_cards(soup):
        if len(jobs) >= max_results:
            break

        anchor_data = _find_job_anchor(card)
        if anchor_data is None:
            continue
        title_anchor, job_url = anchor_data

        if job_url in seen_urls:
            continue

        title = extract_title(card, title_anchor)
        if not title:
            continue

        jobs.append(
            JobOffer(
                title=title,
                company=extract_company(card),
                location=extract_location(card),
                url=job_url,
                source="Computrabajo",
            )
        )
        seen_urls.add(job_url)

    return jobs


# ==============================================================================
# SCRAPER DE COMPUTRABAJO
# ==============================================================================
class ComputrabajoScraper:
    def __init__(
        self,
        headless: bool = False,
        timeout: int = DEFAULT_TIMEOUT,
        max_results: int = DEFAULT_MAX_RESULTS,
        retries: int = DEFAULT_RETRIES,
    ) -> None:
        if timeout <= 0:
            raise ValueError("timeout debe ser mayor que cero")
        if max_results <= 0:
            raise ValueError("max_results debe ser mayor que cero")
        if retries <= 0:
            raise ValueError("retries debe ser mayor que cero")

        self.headless = headless
        self.timeout = timeout
        self.max_results = max_results
        self.retries = retries
        self.jobs: list[JobOffer] = []
        self.driver = None

    def _create_driver(self) -> webdriver.Chrome:
        # Detección de entorno: en servidores o Codespaces no hay pantalla
        # física, así que headless se fuerza automáticamente.
        force_headless = self.headless or runs_without_display()
        if force_headless and not self.headless:
            logger.warning(
                "No se detectó pantalla gráfica (entorno Codespaces/CI/servidor): "
                "se activa el modo headless automáticamente."
            )

        chrome_options = Options()

        if force_headless:
            chrome_options.add_argument("--headless=new")
            chrome_options.add_argument("--disable-gpu")

        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-extensions")
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.add_argument("--lang=es-CO")
        chrome_options.add_argument(f"--user-agent={USER_AGENT}")

        # El sandbox de Chrome requiere privilegios que los contenedores no
        # otorgan; se desactiva solo en esos entornos, no en máquinas locales.
        if runs_in_container():
            chrome_options.add_argument("--no-sandbox")

        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option("useAutomationExtension", False)

        try:
            driver = webdriver.Chrome(options=chrome_options)
            driver.set_page_load_timeout(self.timeout)
            try:
                driver.execute_cdp_cmd(
                    "Page.addScriptToEvaluateOnNewDocument",
                    {
                        "source": (
                            'Object.defineProperty(navigator, "webdriver", '
                            "{get: () => undefined})"
                        )
                    },
                )
            except WebDriverException as exc:
                logger.warning("No se pudo aplicar el ajuste anti-detección: %s", exc)
            return driver
        except WebDriverException as exc:
            logger.error(
                "No se pudo iniciar Chrome. Verifica que Chrome esté instalado. Detalle: %s",
                exc,
            )
            raise

    @staticmethod
    def _has_captcha(source: str) -> bool:
        return "captcha" in source.lower() or "verificación de seguridad" in source.lower()

    def _resolve_captcha(self, driver) -> None:
        if self.headless:
            raise RuntimeError(
                "CAPTCHA detectado. Ejecuta el script SIN la bandera '--headless' "
                "para resolverlo manualmente en el navegador."
            )

        logger.warning("CAPTCHA detectado. Resuélvelo en el navegador abierto.")
        print("\n" + "=" * 60)
        print("ACCIÓN REQUERIDA: Resuelve el CAPTCHA en el navegador.")
        print("Cuando termines y veas las ofertas, presiona ENTER aquí...")
        print("=" * 60)
        try:
            input()
        except EOFError as exc:
            raise RuntimeError("No se pudo solicitar la resolución manual del CAPTCHA.") from exc

        try:
            WebDriverWait(driver, self.timeout).until(
                lambda d: not self._has_captcha(d.page_source)
            )
        except TimeoutException:
            logger.warning("El CAPTCHA aún aparece en la página; se continuará de todos modos.")

    def _wait_for_results(self, driver) -> BeautifulSoup:
        try:
            WebDriverWait(driver, self.timeout).until(
                lambda d: d.execute_script("return document.readyState")
                in ("interactive", "complete")
            )
        except TimeoutException:
            logger.warning("La página tardó más de %s s en cargar.", self.timeout)

        # Retraso aleatorio para simular comportamiento humano y evitar rate limiting
        time.sleep(random.uniform(1.0, 2.5))

        captcha_handled = False
        deadline = time.monotonic() + min(self.timeout, 10)

        while True:
            source = driver.page_source
            soup = BeautifulSoup(source, "html.parser")

            if self._has_captcha(source):
                if captcha_handled:
                    logger.warning("El CAPTCHA continúa presente en la página.")
                    return soup
                self._resolve_captcha(driver)
                captcha_handled = True
                deadline = time.monotonic() + min(self.timeout, 10)
                continue

            if find_job_cards(soup) or looks_like_no_results(soup):
                return soup

            if time.monotonic() >= deadline:
                logger.warning("No se detectaron tarjetas de ofertas en la página.")
                logger.debug("Tamaño del HTML recibido: %s bytes", len(source))
                return soup

            time.sleep(0.5)

    def scrape_computrabajo(self, keyword: str, location: str = "") -> list[JobOffer]:
        keyword = keyword.strip()
        if not keyword:
            raise ValueError("El término de búsqueda no puede estar vacío")

        url = build_search_url(keyword, location)
        logger.info("Iniciando búsqueda: '%s' en '%s'", keyword, location or "Colombia")
        logger.info("URL: %s", url)

        self.jobs = []
        last_error: Optional[Exception] = None

        for attempt in range(1, self.retries + 1):
            driver = None
            try:
                driver = self._create_driver()
                self.driver = driver

                driver.get(url)
                soup = self._wait_for_results(driver)

                self.jobs = parse_jobs(str(soup), self.max_results)
                logger.info("Total extraído exitosamente: %s ofertas", len(self.jobs))
                return self.jobs

            except KeyboardInterrupt:
                raise

            except Exception as exc:
                last_error = exc
                logger.error("Error en scraping (intento %s de %s): %s", attempt, self.retries, exc)
                if attempt < self.retries:
                    logger.info("Reintentando en 3 segundos...")
                    time.sleep(3)

            finally:
                self.driver = None
                if driver is not None:
                    try:
                        driver.quit()
                    except WebDriverException:
                        pass

        if last_error is not None:
            raise RuntimeError(
                f"No se pudo completar la búsqueda tras {self.retries} intentos: {last_error}"
            ) from last_error
        return []

    def save_to_csv(self, filename: Optional[str] = None) -> str:
        if not self.jobs:
            logger.error("No hay ofertas para guardar.")
            return ""

        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"empleos_computrabajo_{timestamp}.csv"

        path = Path(filename).expanduser()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("w", newline="", encoding="utf-8-sig") as file:
                writer = csv.writer(
                    file,
                    delimiter=";",
                    quotechar='"',
                    quoting=csv.QUOTE_ALL,
                )
                writer.writerow(CSV_HEADERS)
                writer.writerows(job.to_csv_row() for job in self.jobs)

            resolved = path.resolve()
            logger.info(
                "Archivo creado exitosamente: %s (%s bytes)",
                resolved,
                resolved.stat().st_size,
            )
            return str(resolved)

        except OSError as exc:
            logger.error("Error guardando CSV en '%s': %s", path, exc)
            return ""

    def print_results(self) -> None:
        if not self.jobs:
            print("\nNo hay resultados")
            return

        print("\n" + "=" * 80)
        print(" RESULTADOS ".center(80, "="))
        print("=" * 80)

        for index, job in enumerate(self.jobs, 1):
            print(f"\n{index}. {job.title}")
            print(f"   Empresa: {job.company}")
            print(f"   Ubicación: {job.location}")
            print(f"   URL: {job.url}")
            print("-" * 80)

        print(f"\nTotal: {len(self.jobs)} ofertas")


# ==============================================================================
# CLI
# ==============================================================================
def positive_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("debe ser un número entero") from exc
    if number <= 0:
        raise argparse.ArgumentTypeError("debe ser mayor que cero")
    return number


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Busca ofertas de trabajo en Computrabajo y guarda un CSV.",
        epilog=(
            "Aviso legal: este software es exclusivamente para fines educativos y "
            "personales. Respeta los términos de uso de Computrabajo."
        ),
    )
    parser.add_argument(
        "keyword",
        nargs="?",
        help="Puesto o palabra clave (si se omite, se solicita por consola)",
    )
    parser.add_argument(
        "location",
        nargs="?",
        help="Ciudad (opcional)",
    )
    parser.add_argument(
        "-o",
        "--output",
        help="Ruta del archivo CSV de salida",
    )
    parser.add_argument(
        "-y",
        "--accept-terms",
        action="store_true",
        help="Acepta el aviso legal y ético de forma programática (útil en automatizaciones y CI)",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Ejecuta Chrome sin interfaz gráfica (no permite resolver CAPTCHA manualmente)",
    )
    parser.add_argument(
        "--timeout",
        type=positive_int,
        default=DEFAULT_TIMEOUT,
        help=f"Tiempo máximo de espera por página (default: {DEFAULT_TIMEOUT})",
    )
    parser.add_argument(
        "--max-results",
        type=positive_int,
        default=DEFAULT_MAX_RESULTS,
        help=f"Máximo de ofertas a extraer (default: {DEFAULT_MAX_RESULTS})",
    )
    parser.add_argument(
        "--retries",
        type=positive_int,
        default=DEFAULT_RETRIES,
        help=f"Intentos totales ante errores (default: {DEFAULT_RETRIES})",
    )
    return parser


def _prompt(label: str) -> str:
    try:
        return input(label).strip()
    except EOFError:
        return ""


def main(argv: Optional[list[str]] = None) -> int:
    setup_logging()
    args = build_arg_parser().parse_args(argv)

    print("=" * 80)
    print(" BUSCADOR - COMPUTRABAJO ".center(80, "="))
    print("=" * 80)

    # Gate de cumplimiento: el aviso legal debe aceptarse antes de cualquier acción.
    if not display_legal_notice(args.accept_terms):
        print("\nDebes aceptar el aviso legal y ético para continuar.")
        print("Ejecuta de nuevo y acepta, o usa la bandera --accept-terms si estás de acuerdo.")
        return 2

    keyword = args.keyword if args.keyword is not None else _prompt("\nPuesto: ")
    if not keyword.strip():
        print("Debes ingresar un puesto o palabra clave.")
        return 2

    if args.keyword is None:
        location = _prompt("Ciudad: ")
    else:
        location = args.location or ""

    scraper = ComputrabajoScraper(
        headless=args.headless,
        timeout=args.timeout,
        max_results=args.max_results,
        retries=args.retries,
    )

    try:
        print("\nBuscando...")
        jobs = scraper.scrape_computrabajo(keyword, location)

        if not jobs:
            print("\nNo se encontraron resultados.")
            print(f"Consejo: revisa el archivo '{LOG_FILE}' para ver si hubo un bloqueo.")
            return 1

        scraper.print_results()

        print("\nGuardando archivo...")
        csv_file = scraper.save_to_csv(args.output)
        if not csv_file:
            print("\nNo se pudo guardar el CSV.")
            print(f"Revisa el archivo '{LOG_FILE}' para más detalles.")
            return 1

        print("\n" + "=" * 80)
        print(" COMPLETADO ".center(80, "="))
        print(f"Archivo: {csv_file}")
        print("=" * 80)
        return 0

    except KeyboardInterrupt:
        print("\n\nCancelado por el usuario.")
        return 130

    except Exception as exc:
        logger.error("Error crítico: %s", exc, exc_info=True)
        print(f"\nError: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())