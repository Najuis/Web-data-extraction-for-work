# Web-data-extraction-for-work

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Status](https://img.shields.io/badge/Status-Producción-success.svg)]()

Extractor robusto y automatizado de ofertas de trabajo de [Computrabajo Colombia](https://www.computrabajo.com.co), implementado en Python utilizando **Selenium** y **BeautifulSoup**. 

Diseñado con principios de ingeniería de software, este proyecto prioriza la resiliencia ante cambios en el DOM, la integridad de los datos extraídos, la evasión básica de detección de bots y la compatibilidad total tanto en entornos locales como en la nube (GitHub Codespaces, CI/CD).

---

## 📋 Requisitos Previos

- **Python:** Versión 3.10 o superior.
- **Navegador:** Google Chrome o Chromium instalado en el sistema. *(Nota: Selenium Manager descarga y gestiona el ChromeDriver compatible de forma automática y transparente)*.
- **Entorno:** Totalmente compatible con Windows, macOS, Linux y entornos en la nube sin interfaz gráfica (GitHub Codespaces, contenedores Docker).

---

## ⚙️ Instalación

Se recomienda encarecidamente el uso de un entorno virtual para aislar las dependencias del proyecto y evitar conflictos con otros paquetes del sistema.

```bash
# 1. Crear el entorno virtual
python3 -m venv .venv

# 2. Activar el entorno virtual
# En Linux / macOS / GitHub Codespaces:
source .venv/bin/activate
# En Windows (CMD):
.venv\Scripts\activate
# En Windows (PowerShell):
.venv\Scripts\Activate.ps1

# 3. Instalar las dependencias
pip install -r requirements.txt