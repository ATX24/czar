"""HTML report generator using Jinja2."""
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Union

from jinja2 import Environment, FileSystemLoader

from .digest_generator import WeeklyDigest

logger = logging.getLogger(__name__)


class HTMLReportGenerator:
    """Generates HTML reports from weekly digests."""

    def __init__(
        self,
        template_dir: Optional[Path] = None,
        output_dir: Optional[Path] = None
    ):
        if template_dir is None:
            template_dir = Path(__file__).parent / "templates"
        if output_dir is None:
            output_dir = Path(__file__).parent.parent / "outputs"

        self.template_dir = template_dir
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.env = Environment(
            loader=FileSystemLoader(str(template_dir)),
            autoescape=True
        )

        # Register filters
        self.env.filters["format_date"] = self._format_date
        self.env.filters["source_badge"] = self._source_badge
        self.env.filters["driver_label"] = self._driver_label

    @staticmethod
    def _format_date(dt: datetime) -> str:
        """Format datetime for display."""
        return dt.strftime("%B %d, %Y")

    @staticmethod
    def _source_badge(source: str) -> str:
        """Get badge HTML for a source."""
        colors = {
            "hn": "#ff6600",
            "reddit": "#ff4500",
            "x": "#1da1f2",
            "github": "#333",
            "youtube": "#ff0000"
        }
        labels = {
            "hn": "HN",
            "reddit": "Reddit",
            "x": "X",
            "github": "GitHub",
            "youtube": "YouTube"
        }
        color = colors.get(source, "#666")
        label = labels.get(source, source.upper())
        return f'<span class="badge" style="background-color: {color}">{label}</span>'

    @staticmethod
    def _driver_label(driver: Optional[str]) -> str:
        """Get human-readable driver label."""
        labels = {
            "new_paper": "New Research",
            "new_repo": "New Repo",
            "benchmark": "Benchmark",
            "product_launch": "Launch"
        }
        return labels.get(driver, "") if driver else ""

    def generate(self, digest: WeeklyDigest) -> Path:
        """
        Generate HTML report from digest.

        Args:
            digest: WeeklyDigest object

        Returns:
            Path to generated HTML file
        """
        template = self.env.get_template("digest.html.jinja2")

        # Format week identifier
        start_date = digest.date_range[0]
        week_num = start_date.isocalendar()[1]
        year = start_date.year
        filename = f"digest_{year}-W{week_num:02d}.html"

        html_content = template.render(
            digest=digest,
            year=year,
            week_num=week_num
        )

        output_path = self.output_dir / filename
        output_path.write_text(html_content)

        logger.info(f"Generated HTML report: {output_path}")
        return output_path
