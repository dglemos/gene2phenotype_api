from collections import OrderedDict
from simple_history.utils import update_change_reason

from django.core.management.base import BaseCommand, CommandError

from gene2phenotype_app.models import (
    CurationData,
    LGDMolecularMechanismEvidence,
    User,
)

"""
Command to recover data from the cutation history table.
It fetches the mechanism evidence description from history and
populates the table lgd_molecular_mechanism_evidence with the
missing descriptions.
Why we need this? There was a bug in the code that was ignoring
the mechanism description. Curators asked us to recover the data.
"""

class Command(BaseCommand):
    def handle(self, *args, **options):
        # Fetch curation data from the history table
        curation_history_all = CurationData.history.all().order_by("id", "-date_last_update")

        latest_per_id = OrderedDict()
        data_to_move = {}

        # Get user info
        try:
            user_obj = User.objects.get(email="dlemos@ebi.ac.uk")
        except Exception as e:
            raise CommandError(str(e))

        for curation_record in curation_history_all:
            if curation_record.id not in latest_per_id:
                latest_per_id[curation_record.stable_id.stable_id] = curation_record.json_data

        for g2p_id in latest_per_id:
            for mechanism_data in latest_per_id[g2p_id]['mechanism_evidence']:
                if g2p_id not in data_to_move:
                    data_to_move[g2p_id] = {}
                    data_to_move[g2p_id][mechanism_data["pmid"]] = mechanism_data["description"]
                else:
                    data_to_move[g2p_id][mechanism_data["pmid"]] = mechanism_data["description"]

        for data_g2p_id in data_to_move:
            descriptions = data_to_move[data_g2p_id]
            # Get the mechanism evidence for the stable_id
            lgd_evidence_list = LGDMolecularMechanismEvidence.objects.filter(
                lgd__stable_id__stable_id=data_g2p_id,
                lgd__stable_id__is_live=1,
                is_deleted=0
            )

            # Check the existing evidence data
            # Only add the description if it is not there
            for lgd_evidence_obj in lgd_evidence_list:
                publication_pmid = lgd_evidence_obj.publication.pmid
                if (not lgd_evidence_obj.description and str(publication_pmid) in descriptions and
                    descriptions[str(publication_pmid)] != ""):
                    print(f"Adding missing mechanism description for {data_g2p_id} and PMID:{publication_pmid}")
                    lgd_evidence_obj.description=descriptions[str(publication_pmid)]
                    lgd_evidence_obj._history_user = user_obj
                    try:
                        lgd_evidence_obj.save()
                    except Exception as e:
                        raise CommandError(str(e))
                    