import tempfile
import unittest
from pathlib import Path

from SCR import (
    ComputrabajoScraper,
    JobOffer,
    build_search_url,
    is_allowed_job_url,
    parse_jobs,
)

SAMPLE_HTML = """
<html><body>
<article class="box_offer" data-id="1">
  <h2 class="fs18 fwB prB">
    <a class="js-o-link fc_base"
       href="/ofertas-de-trabajo/oferta-de-trabajo-de-dev-python-en-bogota-1#lc=1">
      Desarrollador Python
    </a>
  </h2>
  <p class="dFlex vm_fx fs16 fc_base mt5">
    <a class="fc_base t_ellipsis" href="https://co.computrabajo.com/empresas/acme">
      ACME S.A.S
    </a>
  </p>
  <p class="fs16 fc_base mt5">
    <span class="mr10">Bogotá, D.C.</span>
  </p>
</article>
<article class="box_offer" data-id="2">
  <h2><a class="js-o-link" href="/ofertas-de-trabajo/oferta-de-trabajo-de-analista-2">Analista de datos</a></h2>
  <p class="dFlex vm_fx fs16 fc_base mt5">
    <span class="fx_none mr10">4,3</span>Importante empresa del sector
  </p>
  <p class="fs16 fc_base mt5"><span class="mr10">Medellín</span></p>
</article>
<article class="box_offer" data-id="3">
  <h2><a class="js-o-link" href="/ofertas-de-trabajo/oferta-de-trabajo-de-dev-python-en-bogota-1">Duplicada</a></h2>
</article>
<article class="box_offer" data-id="4">
  <h2><a href="https://evil.example/ofertas-de-trabajo/oferta-de-trabajo-de-x">Externa</a></h2>
</article>
</body></html>
"""


class TestBuildSearchUrl(unittest.TestCase):
    def test_encodes_parameters(self):
        url = build_search_url("python developer", "Bogotá D.C.")
        self.assertIn("q=python+developer", url)
        self.assertIn("l=Bogot%C3%A1+D.C.", url)
        self.assertTrue(url.startswith("https://www.computrabajo.com.co/"))

    def test_omits_empty_location(self):
        self.assertNotIn("&l=", build_search_url("python", "  "))


class TestJobOffer(unittest.TestCase):
    def test_cleans_text(self):
        job = JobOffer(
            title="  Desarrollador\n  Python  ",
            company="ACME\r\n S.A.S",
            location=" Bogotá ",
            url="https://www.computrabajo.com.co/x",
        )
        self.assertEqual(job.title, "Desarrollador Python")
        self.assertEqual(job.company, "ACME S.A.S")
        self.assertEqual(job.location, "Bogotá")

    def test_prevents_csv_injection(self):
        self.assertEqual(JobOffer.sanitize_csv_cell("=SUM(A1)"), "'=SUM(A1)")
        self.assertEqual(JobOffer.sanitize_csv_cell("@cmd"), "'@cmd")
        self.assertEqual(JobOffer.sanitize_csv_cell("Normal"), "Normal")


class TestUrlValidation(unittest.TestCase):
    def test_allows_computrabajo_hosts(self):
        self.assertTrue(
            is_allowed_job_url(
                "https://www.computrabajo.com.co/ofertas-de-trabajo/oferta-de-trabajo-de-x"
            )
        )
        self.assertTrue(
            is_allowed_job_url(
                "https://subdominio.computrabajo.com.co/ofertas-de-trabajo/x"
            )
        )

    def test_rejects_external_and_unsafe_urls(self):
        self.assertFalse(is_allowed_job_url("https://evil.example/oferta"))
        self.assertFalse(is_allowed_job_url("http://www.computrabajo.com.co/oferta"))
        self.assertFalse(is_allowed_job_url("javascript:alert(1)"))
        self.assertFalse(is_allowed_job_url("https://computrabajo.com.co.evil.example/"))


class TestParseJobs(unittest.TestCase):
    def test_extracts_and_deduplicates_offers(self):
        jobs = parse_jobs(SAMPLE_HTML)

        self.assertEqual(len(jobs), 2)
        self.assertEqual(jobs[0].title, "Desarrollador Python")
        self.assertEqual(jobs[0].company, "ACME S.A.S")
        self.assertEqual(jobs[0].location, "Bogotá, D.C.")
        self.assertEqual(
            jobs[0].url,
            "https://www.computrabajo.com.co/ofertas-de-trabajo/"
            "oferta-de-trabajo-de-dev-python-en-bogota-1",
        )
        self.assertEqual(jobs[1].company, "Importante empresa del sector")
        self.assertEqual(jobs[1].location, "Medellín")

    def test_respects_max_results(self):
        self.assertEqual(len(parse_jobs(SAMPLE_HTML, max_results=1)), 1)

    def test_returns_empty_list_for_empty_html(self):
        self.assertEqual(parse_jobs("<html><body></body></html>"), [])

    def test_rejects_invalid_max_results(self):
        with self.assertRaises(ValueError):
            parse_jobs(SAMPLE_HTML, max_results=0)


class TestSaveCsv(unittest.TestCase):
    def test_writes_csv_with_injection_protection(self):
        scraper = ComputrabajoScraper()
        scraper.jobs = [
            JobOffer(
                title="=HYPERLINK(\"http://evil\")",
                company="ACME",
                location="Bogotá",
                url="https://www.computrabajo.com.co/x",
            )
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "ofertas.csv"
            result = scraper.save_to_csv(str(output))

            self.assertTrue(result)
            self.assertTrue(output.exists())
            content = output.read_text(encoding="utf-8-sig")
            self.assertIn("'=HYPERLINK", content)
            self.assertIn("Título", content)

    def test_returns_empty_when_no_jobs(self):
        self.assertEqual(ComputrabajoScraper().save_to_csv(), "")


if __name__ == "__main__":
    unittest.main()
