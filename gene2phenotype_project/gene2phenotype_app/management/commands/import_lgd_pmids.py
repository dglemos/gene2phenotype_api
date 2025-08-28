import csv
import re
import logging

from django.db.models import Prefetch
from django.core.management.base import BaseCommand, CommandError

from ...utils import get_publication, get_authors, clean_title, get_date_now

from gene2phenotype_app.models import (
    Publication,
    LGDPublication,
    LocusGenotypeDisease,
    User,
)


"""
Command to import pmids from a csv file.
The pmids are associated with old G2P records, before adding the pmid we have to check
if it's possible to fetch the current record.
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

    def handle(self, *args, **options):
        data_file = options["data_file"]
        input_email = options["email"]
        output_file = "output_data.txt"
        unique_current_g2p_ids = []

        # Get user info
        try:
            user_obj = User.objects.get(email=input_email)
        except Exception as e:
            raise CommandError(str(e))

        with open(data_file, newline="", encoding='latin-1') as fh_file, open(output_file, "w") as wr:
            data_reader = csv.DictReader(fh_file)
            for row in data_reader:
                output_comment = ""
                record_to_update = None
                gene_symbol = row["gene symbol"].strip()
                genotype = row["allelic requirement"].strip().replace("\'", "")
                disease_name = row["disease name"].strip().replace("\'", "")
                variant_consequence = row["variant consequence"].strip().replace("_variant", "").replace("_", " ")

                if genotype == "monoallelic_X_hem":
                    genotype = "monoallelic_X_hemizygous"

                if not gene_symbol:
                    raise CommandError(f"Gene symbol is missing: {str(row)}")

                g2p_updated = row["g2p_updated"]
                if g2p_updated and "added publications" in g2p_updated:
                    wr.write(f"{row['id']}\tAlready updated\n")
                    continue

                # Get records linked to the gene symbol
                lgd_records = LocusGenotypeDisease.objects.filter(
                    locus__name = gene_symbol,
                    is_deleted = 0
                )

                if len(lgd_records) > 1:
                    # print(f"\nCannot find unique record for {gene_symbol} trying to find a match...")
                    tmp_record = None
                    for record in lgd_records:
                        # print(f"{gene_symbol} ({genotype}; {disease_name}; {variant_consequence}) > found {record.stable_id.stable_id}; {record.genotype}; {record.disease.name}; {record.mechanism.value}")

                        if str(record.genotype) == genotype and variant_consequence and variant_consequence == record.mechanism.value:
                            tmp_record = record
                            # print(f"(1) {record.genotype} = {genotype}")
                        else:
                            record_disease_new = re.sub(f"{gene_symbol}-related ", "", record.disease.name)
                            if record_disease_new.lower() in disease_name.lower() and str(record.genotype) == genotype:
                                tmp_record = record
                                # print(f"(2) {record.genotype} = {genotype}; {record_disease_new} in {disease_name}")

                    if not tmp_record:
                        logger.warning(f"Cannot find unique record for {gene_symbol}")
                        wr.write(f"{row['id']}\tCannot find unique record for {gene_symbol}\n")
                        continue
                    else:
                        record_to_update = tmp_record
                else:
                    # Even though there is only one record in the current db we should check if it's the same
                    tmp_record = lgd_records[0]
                    record_disease_new = re.sub(f"{gene_symbol}-related ", "", tmp_record.disease.name)
                    # print(f"\n{gene_symbol} ({genotype}; {disease_name}; {variant_consequence}) > found {tmp_record.stable_id.stable_id}; {tmp_record.genotype}; {tmp_record.disease.name}; {tmp_record.mechanism.value}")
                    if (str(tmp_record.genotype) == genotype and 
                        (variant_consequence and variant_consequence == tmp_record.mechanism.value or 
                         record_disease_new.lower() in disease_name.lower())
                        ):
                        record_to_update = tmp_record
                    else:
                        wr.write(f"{row['id']}\tCannot find record for {gene_symbol}\n")
                        continue

                # Prepare to update record
                g2p_id = record_to_update.stable_id.stable_id

                if g2p_id not in unique_current_g2p_ids:
                    unique_current_g2p_ids.append(g2p_id)
                else:
                    logger.warning(f"{g2p_id} is already mapped to a record. Check {gene_symbol}")
                    wr.write(f"{row['id']}\t{g2p_id} is already mapped to a record. Check {gene_symbol}\n")
                    continue

                # print(f"\nGoing to update {g2p_id}")
                list_pmids_to_add = row["reviewed_correct_pmids"].strip().split(";")
                existing_ddg2p_pmids_file = row["existing_ddg2p_pmid"].strip()

                # Remove duplicates from the list of pmids to add
                list_pmids_to_add_unique = set(list_pmids_to_add)

                # Get list of pmids already associated with record
                # We want all records even if they are deteled
                lgd_publication_list = LGDPublication.objects.filter(
                    lgd = record_to_update
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
                # print("(file) existing pmids:", existing_ddg2p_pmids_file)
                # print("(file) pmids to add:", list_pmids_to_add_unique)

                # We shouldn't have deleted lgd-publications
                # Kill the import if we have deleted rows
                if existing_pmids_deleted:
                    raise CommandError(f"There are deleted LGD-publication rows. Update the import script.")

                if int(existing_ddg2p_pmids_file) not in existing_pmids:
                    print(f"{g2p_id} is not associated with {existing_ddg2p_pmids_file};")
                    output_comment += f"{g2p_id} is not associated with {existing_ddg2p_pmids_file}; "

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
                                    pmid = int(pmid_to_add)
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
                                    pmid=int(pmid_to_add), title=title, authors=authors, year=year, doi=doi
                                )
                                publication_obj._history_user = user_obj
                                publication_obj.save()

                            # print("Creating lgd publication")
                            # Create LGDPublication
                            lgd_publication_obj = LGDPublication(
                                lgd = record_to_update,
                                publication = publication_obj,
                                is_deleted = 0
                            )
                            lgd_publication_obj._history_user = user_obj
                            lgd_publication_obj.save()

                            output_comment += f"added:{pmid_to_add}; "

                            # Update the record date of last review
                            # record_to_update._history_user = user_obj
                            # record_to_update.date_review = get_date_now()
                            # record_to_update.save()

                wr.write(f"{row['id']}\t{output_comment}\n")

        # Check remaining definitive records with only one publication
        lgd_records_definitive = LocusGenotypeDisease.objects.filter(
            confidence__value = "definitive",
            is_deleted = 0
        ).prefetch_related(
                Prefetch(
                    "lgdpublication_set",
                    queryset=LGDPublication.objects.filter(is_deleted=0),
                    to_attr="publications"
                )
            )

        print("\nDefinitve records with only one publication:")

        for lgd_obj in lgd_records_definitive:
            lgd_publications = lgd_obj.publications

            if len(lgd_publications) == 1:
                print(f"{lgd_obj.stable_id.stable_id}; gene: {lgd_obj.locus.name}; disease: {lgd_obj.disease.name}; genotype: {lgd_obj.genotype.value}; mechanism: {lgd_obj.mechanism.value}")
