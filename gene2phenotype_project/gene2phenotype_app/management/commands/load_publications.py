import csv
import re
import logging

from django.db.models import Prefetch
from django.core.management.base import BaseCommand, CommandError

from ...utils import get_publication, get_authors, clean_title

from gene2phenotype_app.models import (
    Publication,
    LGDPublication,
    LGDMinedPublication,
    LocusGenotypeDisease,
    User,
)


"""
Command to import pmids from a csv file.
The pmids are associated with the new G2P records.
"""

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument(
            "--data_file",
            required=True,
            type=str,
            help="Input file with record pmids to load",
        )
        parser.add_argument(
            "--email",
            required=True,
            type=str,
            help="User email to store in the history table",
        )
        parser.add_argument(
            "--output_definitive",
            required=False,
            type=str,
            help="Output file to write list of definitive records with one publication",
        )

    def handle(self, *args, **options):
        data_file = options["data_file"]
        input_email = options["email"]

        # Prepare output files
        output_definitive = options["output_definitive"]
        output_file = "output_data.txt"
        if not output_definitive:
            output_definitive = "definitive_records_one_publication.txt"

        # Get user info
        try:
            user_obj = User.objects.get(email=input_email)
        except Exception as e:
            raise CommandError(str(e))

        with (
            open(data_file, newline="", encoding='utf-8-sig') as fh_file,
            open(output_file, "w") as wr,
        ):
            data_reader = csv.DictReader(fh_file)
            for row in data_reader:
                output_comment = ""
                g2p_id = row["g2p id"].strip()
                gene_symbol = row["gene symbol"].strip()
                genotype = row["allelic requirement"].strip().replace("'", "")
                disease_name = row["disease name"].strip().replace("'", "")
                list_pmids_to_add = row["new PMIDs"].strip().split("\n")

                # Remove duplicates from the list of pmids to add
                list_pmids_to_add_unique = set(list_pmids_to_add)

                print(f"-> {g2p_id}: {list_pmids_to_add_unique}")

                if not g2p_id:
                    raise CommandError(f"G2P ID is missing: {str(row)}")

                # Get record
                try:
                    lgd_record = LocusGenotypeDisease.objects.get(
                        stable_id__stable_id=g2p_id, is_deleted=0
                    )
                except LocusGenotypeDisease.DoesNotExist:
                    raise CommandError(f"Invalid G2P ID: {g2p_id}")
                else:
                    if (lgd_record.genotype.value != genotype or
                        lgd_record.locus.name != gene_symbol):
                        wr.write(f"{g2p_id}\tdata from file does not match data in G2P: {lgd_record.genotype.value}; {lgd_record.disease.name}\n")
                        continue
                        # print(f"WARNING: {g2p_id} from file does not match data in G2P: {lgd_record.genotype.value}; {lgd_record.disease.name}")

                    # Get list of pmids already associated with record
                    # We want all records even if they are deteled
                    lgd_publication_list = LGDPublication.objects.filter(
                        lgd=lgd_record
                    )

                    existing_pmids = []
                    existing_pmids_deleted = []
                    for lgd_publication in lgd_publication_list:
                        # Check if the existing pmid is flagged as deleted
                        if lgd_publication.is_deleted:
                            existing_pmids_deleted.append(lgd_publication.publication.pmid)
                        else:
                            existing_pmids.append(lgd_publication.publication.pmid)

                    # print("Existing pmids:", existing_pmids)
                    # print("Existing pmids deleted:", existing_pmids_deleted)

                    # We shouldn't have deleted lgd-publications
                    # Kill the import if we have deleted rows
                    if existing_pmids_deleted:
                        raise CommandError(
                            "There are deleted LGD-publication rows. Update the import script."
                        )

                    if not list_pmids_to_add or list_pmids_to_add[0] == "":
                        print(f"No pmids to add for {g2p_id};")
                        output_comment = f"No pmids to add for {g2p_id};"
                    else:
                        for pmid_to_add in list_pmids_to_add_unique:
                            if int(pmid_to_add) not in existing_pmids:
                                # print(f"Adding {pmid_to_add}")

                                # Get or create Publication
                                try:
                                    publication_obj = Publication.objects.get(
                                        pmid=int(pmid_to_add)
                                    )
                                except Publication.DoesNotExist:
                                    response = get_publication(int(pmid_to_add))
                                    if response["hitCount"] == 0:
                                        raise CommandError(f"Invalid PMID {pmid_to_add}")
                                    authors = get_authors(response)
                                    year = None
                                    doi = None
                                    publication_info = response["result"]
                                    title = clean_title(publication_info["title"])
                                    if "doi" in publication_info:
                                        doi = publication_info["doi"]
                                    if "pubYear" in publication_info:
                                        year = publication_info["pubYear"]

                                    # Insert publication
                                    publication_obj = Publication(
                                        pmid=int(pmid_to_add),
                                        title=title,
                                        authors=authors,
                                        year=year,
                                        doi=doi,
                                    )
                                    publication_obj._history_user = user_obj
                                    publication_obj.save()

                                # print("Creating lgd publication")
                                # Create LGDPublication
                                lgd_publication_obj = LGDPublication(
                                    lgd=lgd_record,
                                    publication=publication_obj,
                                    is_deleted=0,
                                )
                                lgd_publication_obj._history_user = user_obj
                                lgd_publication_obj.save()

                                output_comment += f"added:{pmid_to_add}; "

                                # Check if new publication is in mined_publication
                                try:
                                    lgd_mined_publication = LGDMinedPublication.objects.get(
                                        lgd=lgd_record,
                                        mined_publication__pmid=publication_obj.pmid,
                                        status="mined"
                                    )
                                except LGDMinedPublication.DoesNotExist:
                                    continue
                                else:
                                    lgd_mined_publication._history_user = user_obj
                                    lgd_mined_publication.status = "curated"
                                    lgd_mined_publication.save()

                    wr.write(f"{g2p_id}\t{output_comment}\n")

        # Check remaining definitive records with only one publication
        lgd_records_definitive = LocusGenotypeDisease.objects.filter(
            confidence__value="definitive", is_deleted=0
        ).prefetch_related(
            Prefetch(
                "lgdpublication_set",
                queryset=LGDPublication.objects.filter(is_deleted=0),
                to_attr="publications",
            )
        )

        with open(output_definitive, "w") as wr_2:
            wr_2.write("G2P ID\tGene\tDisease\tGenotype\tMechanism\tURL")

            for lgd_obj in lgd_records_definitive:
                lgd_publications = lgd_obj.publications

                if len(lgd_publications) == 1:
                    g2p_id = lgd_obj.stable_id.stable_id
                    url = f"https://www.ebi.ac.uk/gene2phenotype/lgd/{g2p_id}"
                    wr_2.write(
                        f"{g2p_id}\t{lgd_obj.locus.name}\t{lgd_obj.disease.name}\t{lgd_obj.genotype.value}\t{lgd_obj.mechanism.value}\t{url}\n"
                    )
