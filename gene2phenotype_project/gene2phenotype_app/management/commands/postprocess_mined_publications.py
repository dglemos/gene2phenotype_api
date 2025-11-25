import logging

from django.core.management.base import BaseCommand, CommandError
from django.db.models import F, Count

from gene2phenotype_app.models import (
    LGDMinedPublication,
    User,
)


"""
Command to delete mined publication for records with more
than 100 mined publications.

How to run the command:
python manage.py postprocess_mined_publications
"""

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument(
            "--email",
            required=False,
            type=str,
            help="User email to store in the history table",
        )

    def handle(self, *args, **options):
        record_mined_publications_count = self.get_mined_publications_count()

        for g2p_id in record_mined_publications_count:
            publication_to_keep = []
            if record_mined_publications_count[g2p_id] > 100:
                print("->", g2p_id)

                list_lgd_mined_publications = LGDMinedPublication.objects.filter(
                    lgd__stable_id__stable_id=g2p_id,
                    status="mined"
                ).order_by("-mined_publication__year")

                for lgd_mined_publication in list_lgd_mined_publications:
                    if len(publication_to_keep) < 100:
                        publication_to_keep.append(lgd_mined_publication)
                    else:
                        lgd_mined_publication.delete()

    def get_mined_publications_count(self):
        """
        Get all records and associated number of mined publications.
        """
        publication_counts = {}

        lgd_mined_publication_data = (
            LGDMinedPublication.objects.filter(status="mined")
                .annotate(g2p_id=F("lgd__stable_id__stable_id"))
                .values("g2p_id")
                .annotate(publication_count=Count("mined_publication", distinct=True))
                .order_by("g2p_id")
            )

        for publication in lgd_mined_publication_data:
            publication_counts[publication['g2p_id']] = publication['publication_count']

        return publication_counts