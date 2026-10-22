# Web-data-extraction-for-work

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![Selenium](https://img.shields.io/badge/Selenium-4.15%2B-green.svg)](https://www.selenium.dev/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Status](https://img.shields.io/badge/Status-Producción-success.svg)]()

## 🎓 Propósito Educativo

Este proyecto ha sido desarrollado como **material didáctico para el aprendizaje de automatización web con Selenium**. Su objetivo principal es demostrar de manera práctica cómo interactuar programáticamente con sitios web dinámicos, extraer información estructurada y manejar casos reales de scraping ético.

**Casos de uso académico:**
- Cursos de automatización de pruebas web
- Laboratorios de ingeniería de software
- Proyectos de análisis de datos
- Investigación en extracción de información pública
- Práctica de patrones de diseño en scraping

---

## 🤖 ¿Qué es Selenium y Cómo se Utiliza?

### Definición

**Selenium** es un framework de código abierto para automatizar navegadores web. Permite controlar programáticamente un navegador (Chrome, Firefox, Edge, etc.) para realizar acciones como un usuario humano: navegar páginas, hacer clic en elementos, llenar formularios y extraer información.

### Conceptos Fundamentales Implementados en Este Proyecto

#### 1. **WebDriver: El Controlador del Navegador**
```python
# Selenium crea una instancia de Chrome controlada por Python
driver = webdriver.Chrome(options=chrome_options)