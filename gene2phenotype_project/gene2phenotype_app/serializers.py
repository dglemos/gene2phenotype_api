from rest_framework import serializers
from django.db import connection, transaction

from .models import (Panel, User, UserPanel, AttribType, Attrib,
                     LGDPanel, LocusGenotypeDisease, LGDVariantGenccConsequence,
                     LGDCrossCuttingModifier, LGDPublication,
                     LGDPhenotype, LGDVariantType, Locus, Disease,
                     DiseaseOntology, LocusAttrib, DiseaseSynonym, 
                     LocusIdentifier, PublicationComment, LGDComment,
                     DiseasePublication, LGDMolecularMechanism,
                     OntologyTerm, Source, Publication, GeneDisease,
                     Sequence, UniprotAnnotation)

from .utils import clean_string, get_mondo, get_publication, get_authors, validate_gene, validate_phenotype
import re


class PanelDetailSerializer(serializers.ModelSerializer):
    curators = serializers.SerializerMethodField()
    last_updated = serializers.SerializerMethodField()

    # Returns only the curators excluding staff members
    def get_curators(self, id):
        user_panels = UserPanel.objects.filter(panel=id)
        users = []
        for user_panel in user_panels:
            if user_panel.user.is_active == 1 and user_panel.user.is_staff == 0:
                users.append(user_panel.user.username)
        return users

    def get_last_updated(self, id):
        dates = []
        lgd_panels = LGDPanel.objects.filter(panel=id)
        for lgd_panel in lgd_panels:
            if lgd_panel.lgd.date_review is not None and lgd_panel.lgd.is_reviewed == 1 and lgd_panel.lgd.is_deleted == 0:
                dates.append(lgd_panel.lgd.date_review)
                dates.sort()
        if len(dates) > 0:
            return dates[-1].date()
        else:
            return []

    def calculate_stats(self, panel):
        lgd_panels = LGDPanel.objects.filter(panel=panel.id)
        num_records = 0
        genes = 0
        uniq_genes = {}
        diseases = 0
        uniq_diseases = {}
        attrib_id = Attrib.objects.get(value='gene').id
        for lgd_panel in lgd_panels:
            if lgd_panel.is_deleted == 0:
                num_records += 1
                if lgd_panel.lgd.locus.type.id == attrib_id and lgd_panel.lgd.locus.name not in uniq_genes:
                    genes += 1
                    uniq_genes = { lgd_panel.lgd.locus.name:1 }
                if lgd_panel.lgd.disease_id not in uniq_diseases:
                    diseases += 1
                    uniq_diseases = { lgd_panel.lgd.disease_id:1 }

        stats = {
            'number of records': num_records,
            'number of genes': genes,
            'number of disease':diseases
            }

        return stats

    def records_summary(self, panel):
        lgd_panels = LGDPanel.objects.filter(panel=panel.id).filter(is_deleted=0)

        lgd_panels_selected = lgd_panels.select_related('lgd', 'lgd__locus', 'lgd__disease', 'lgd__genotype', 'lgd__confidence'
                                               ).prefetch_related('lgd__lgd_variant_gencc_consequence', 'lgd__lgd_variant_type').order_by('-lgd__date_review').filter(lgd__is_deleted=0)[:100]

        lgd_objects_list = list(lgd_panels_selected.values('lgd__locus__name',
                                                           'lgd__disease__name',
                                                           'lgd__genotype__value',
                                                           'lgd__confidence__value',
                                                           'lgd__lgdvariantgenccconsequence__variant_consequence__term',
                                                           'lgd__lgdvarianttype__variant_type_ot__term',
                                                           'lgd__date_review',
                                                           'lgd__stable_id'))

        aggregated_data = {}
        number_keys = 0
        for lgd_obj in lgd_objects_list:
            if lgd_obj['lgd__stable_id'] not in aggregated_data.keys() and number_keys < 10:
                variant_consequences = []
                variant_types = []

                variant_consequences.append(lgd_obj['lgd__lgdvariantgenccconsequence__variant_consequence__term'])
                # Some records do not have variant types
                if lgd_obj['lgd__lgdvarianttype__variant_type_ot__term'] is not None:
                    variant_types.append(lgd_obj['lgd__lgdvarianttype__variant_type_ot__term'])

                aggregated_data[lgd_obj['lgd__stable_id']] = {  'locus':lgd_obj['lgd__locus__name'],
                                                                'disease':lgd_obj['lgd__disease__name'],
                                                                'genotype':lgd_obj['lgd__genotype__value'],
                                                                'confidence':lgd_obj['lgd__confidence__value'],
                                                                'variant_consequence':variant_consequences,
                                                                'variant_type':variant_types,
                                                                'date_review':lgd_obj['lgd__date_review'],
                                                                'stable_id':lgd_obj['lgd__stable_id'] }
                number_keys += 1

            elif number_keys < 10:
                if lgd_obj['lgd__lgdvariantgenccconsequence__variant_consequence__term'] not in aggregated_data[lgd_obj['lgd__stable_id']]['variant_consequence']:
                    aggregated_data[lgd_obj['lgd__stable_id']]['variant_consequence'].append(lgd_obj['lgd__lgdvariantgenccconsequence__variant_consequence__term'])
                if lgd_obj['lgd__lgdvarianttype__variant_type_ot__term'] not in aggregated_data[lgd_obj['lgd__stable_id']]['variant_type'] and lgd_obj['lgd__lgdvarianttype__variant_type_ot__term'] is not None:
                    aggregated_data[lgd_obj['lgd__stable_id']]['variant_type'].append(lgd_obj['lgd__lgdvarianttype__variant_type_ot__term'])

        return aggregated_data.values()

    class Meta:
        model = Panel
        fields = ['name', 'description', 'curators', 'last_updated']

class UserSerializer(serializers.ModelSerializer):
    user = serializers.CharField(read_only=True, source="username")
    email = serializers.CharField(read_only=True)
    panels = serializers.SerializerMethodField()
    is_active = serializers.CharField(read_only=True)

    def get_panels(self, id):
        user_login = self.context.get('user_login')
        user_panels = UserPanel.objects.filter(user=id)
        panels_list = []

        for user_panel in user_panels:
            # Authenticated users can view all panels
            if (user_login and user_login.is_authenticated) or user_panel.panel.is_visible == 1:
                panels_list.append(user_panel.panel.name)

        return panels_list

    class Meta:
        model = User
        fields = ['user', 'email', 'is_active', 'panels']

class AttribTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = AttribType
        fields = ['code']

class AttribSerializer(serializers.ModelSerializer):
    class Meta:
        model = Attrib
        fields = ['value']

class LGDPanelSerializer(serializers.ModelSerializer):
    panel = serializers.CharField(source="panel.name")

    class Meta:
        model = LGDPanel
        fields = ['panel']

class LocusSerializer(serializers.ModelSerializer):
    gene_symbol = serializers.CharField(source="name")
    sequence = serializers.CharField(source="sequence.name")
    reference = serializers.CharField(read_only=True, source="sequence.reference.value")
    ids = serializers.SerializerMethodField()
    synonyms = serializers.SerializerMethodField()

    def get_ids(self, id):
        locus_ids = LocusIdentifier.objects.filter(locus=id)
        data = {}
        for id in locus_ids:
            data[id.source.name] = id.identifier

        return data

    def get_synonyms(self, id):
        attrib_type_obj = AttribType.objects.filter(code='gene_synonym')
        locus_attribs = LocusAttrib.objects.filter(locus=id, attrib_type=attrib_type_obj.first().id, is_deleted=0)
        data = []
        for locus_atttrib in locus_attribs:
            data.append(locus_atttrib.value)

        return data

    @transaction.atomic
    def create(self, validated_data):
        gene_symbol = validated_data.get('name')
        sequence_name = validated_data.get('sequence')['name']
        start = validated_data.get('start')
        end = validated_data.get('end')
        strand = validated_data.get('strand')

        locus_obj = None
        try:
            locus_obj = Locus.objects.get(name=gene_symbol)
            raise serializers.ValidationError({"message": f"gene already exists",
                                               "please select existing gene": f"{locus_obj.name} {locus_obj.sequence.name}:{locus_obj.start}-{locus_obj.end}"})
        except Locus.DoesNotExist:
            try:
                # Check if gene symbol is a synonym
                synonym_obj = LocusAttrib.objects.get(value=gene_symbol)
                raise serializers.ValidationError({"message": f"gene already exists as a synonym",
                                               "please select existing gene": f"{synonym_obj.locus.name} {synonym_obj.locus.sequence.name}:{synonym_obj.locus.start}-{synonym_obj.locus.end}"})
            except LocusAttrib.DoesNotExist:
                # Validate gene before insertion
                validated = validate_gene(gene_symbol)
                if validated == None:
                    raise serializers.ValidationError({"message": f"invalid gene symbol",
                                                       "please check symbol": gene_symbol})

                # Insert locus gene
                sequence = Sequence.objects.filter(name=sequence_name)
                type = Attrib.objects.filter(value='gene')

                locus_obj = Locus.objects.create(name = gene_symbol,
                                                 sequence = sequence.first(),
                                                 start = start,
                                                 end = end,
                                                 strand = strand,
                                                 type = type.first())

                # Insert gene-disease associations from OMIM
                source_omim = Source.objects.filter(name='OMIM')
                if 'mim' in validated.keys():
                    for mim in validated['mim']:
                        gene_disease_obj = GeneDisease.objects.create(disease=mim['disease'],
                                                                      gene=locus_obj,
                                                                      source=source_omim.first(),
                                                                      identifier=mim['id'])

                # Insert locus gene synonyms
                if 'synonyms' in validated.keys():
                    attrib_type_obj = AttribType.objects.filter(code='gene_synonym')
                    for synonym in validated['synonyms']:
                        locus_attrib_obj = LocusAttrib.objects.create(value=synonym,
                                                                      locus=locus_obj,
                                                                      attrib_type=attrib_type_obj.first(),
                                                                      is_deleted=0)

                # Insert locus gene ids
                source_hgnc = Source.objects.filter(name='HGNC')
                source_ensembl = Source.objects.filter(name='Ensembl')
                locus_identifier_obj = LocusIdentifier.objects.create(identifier=validated['primary_id'],
                                                                      locus=locus_obj,
                                                                      source=source_hgnc.first())
                locus_identifier_obj = LocusIdentifier.objects.create(identifier=validated['ensembl_id'],
                                                                      locus=locus_obj,
                                                                      source=source_ensembl.first())

        return locus_obj

    class Meta:
        model = Locus
        fields = ['gene_symbol', 'sequence', 'start', 'end', 'strand', 'reference', 'ids', 'synonyms']

class LocusGeneSerializer(LocusSerializer):
    last_updated = serializers.SerializerMethodField()

    def get_last_updated(self, id):
        dates = []
        lgds = LocusGenotypeDisease.objects.filter(locus=id)
        for lgd in lgds:
            if lgd.date_review is not None and lgd.is_reviewed == 1 and lgd.is_deleted == 0:
                dates.append(lgd.date_review)
                dates.sort()
        if len(dates) > 0:
            return dates[-1].date()
        else:
            return []

    def records_summary(self, user):
        lgd_list = LocusGenotypeDisease.objects.filter(locus=self.id, is_deleted=0)

        if user.is_authenticated:
            lgd_select = lgd_list.select_related('disease', 'genotype', 'confidence'
                                               ).prefetch_related('lgd_panel', 'panel', 'lgd_variant_gencc_consequence', 'lgd_variant_type'
                                                                  ).order_by('-date_review')

        else:
            lgd_select = lgd_list.select_related('disease', 'genotype', 'confidence'
                                               ).prefetch_related('lgd_panel', 'panel', 'lgd_variant_gencc_consequence', 'lgd_variant_type'
                                                                  ).order_by('-date_review').filter(lgdpanel__panel__is_visible=1)

        lgd_objects_list = list(lgd_select.values('disease__name',
                                                  'lgdpanel__panel__name',
                                                  'stable_id',
                                                  'genotype__value',
                                                  'confidence__value',
                                                  'lgdvariantgenccconsequence__variant_consequence__term',
                                                  'lgdvarianttype__variant_type_ot__term'))

        aggregated_data = {}
        for lgd_obj in lgd_objects_list:
            if lgd_obj['stable_id'] not in aggregated_data.keys():
                variant_consequences = []
                variant_types = []
                panels = []

                panels.append(lgd_obj['lgdpanel__panel__name'])
                variant_consequences.append(lgd_obj['lgdvariantgenccconsequence__variant_consequence__term'])
                if lgd_obj['lgdvarianttype__variant_type_ot__term'] is not None:
                    variant_types.append(lgd_obj['lgdvarianttype__variant_type_ot__term'])

                aggregated_data[lgd_obj['stable_id']] = { 'disease':lgd_obj['disease__name'],
                                                          'genotype':lgd_obj['genotype__value'],
                                                          'confidence':lgd_obj['confidence__value'],
                                                          'panels':panels,
                                                          'variant_consequence':variant_consequences,
                                                          'variant_type':variant_types,
                                                          'stable_id':lgd_obj['stable_id'] }

            else:
                if lgd_obj['lgdpanel__panel__name'] not in aggregated_data[lgd_obj['stable_id']]['panels']:
                    aggregated_data[lgd_obj['stable_id']]['panels'].append(lgd_obj['lgdpanel__panel__name'])
                if lgd_obj['lgdvariantgenccconsequence__variant_consequence__term'] not in aggregated_data[lgd_obj['stable_id']]['variant_consequence']:
                    aggregated_data[lgd_obj['stable_id']]['variant_consequence'].append(lgd_obj['lgdvariantgenccconsequence__variant_consequence__term'])
                if lgd_obj['lgdvarianttype__variant_type_ot__term'] not in aggregated_data[lgd_obj['stable_id']]['variant_type'] and lgd_obj['lgdvarianttype__variant_type_ot__term'] is not None:
                    aggregated_data[lgd_obj['stable_id']]['variant_type'].append(lgd_obj['lgdvarianttype__variant_type_ot__term'])

        return aggregated_data.values()

    def function(self):
        result_data = {}
        uniprot_annotation_objs = UniprotAnnotation.objects.filter(gene=self.id)

        for function_obj in uniprot_annotation_objs:
            result_data['protein_function'] = function_obj.protein_function
            result_data['uniprot_accession'] = function_obj.uniprot_accession

        return result_data

    class Meta:
        model = Locus
        fields = LocusSerializer.Meta.fields + ['last_updated']

class GeneDiseaseSerializer(serializers.ModelSerializer):
    disease = serializers.CharField()
    identifier = serializers.CharField()
    source = serializers.CharField(source="source.name")

    class Meta:
        model = GeneDisease
        fields = ['disease', 'identifier', 'source']

class LocusGenotypeDiseaseSerializer(serializers.ModelSerializer):
    locus = serializers.SerializerMethodField()
    genotype = serializers.CharField(source="genotype.value", read_only=True)
    variant_consequence = serializers.SerializerMethodField()
    molecular_mechanism = serializers.SerializerMethodField()
    disease = serializers.SerializerMethodField()
    confidence = serializers.CharField(source="confidence.value", read_only=True)
    publications = serializers.SerializerMethodField()
    panels = serializers.SerializerMethodField()
    cross_cutting_modifier = serializers.SerializerMethodField()
    variant_type = serializers.SerializerMethodField()
    phenotypes = serializers.SerializerMethodField()
    last_updated = serializers.SerializerMethodField()
    date_created = serializers.SerializerMethodField()
    comments = serializers.SerializerMethodField()
    is_reviewed = serializers.IntegerField(read_only=True)

    def get_locus(self, id):
        locus = LocusSerializer(id.locus).data
        return locus

    def get_disease(self, id):
        disease = DiseaseSerializer(id.disease).data
        return disease

    def get_last_updated(self, obj):
        return obj.date_review.strftime("%Y-%m-%d")

    def get_variant_consequence(self, id):
        queryset = LGDVariantGenccConsequence.objects.filter(lgd_id=id)
        return VariantConsequenceSerializer(queryset, many=True).data

    def get_molecular_mechanism(self, id):
        queryset = LGDMolecularMechanism.objects.filter(lgd_id=id)
        return LGDMolecularMechanismSerializer(queryset, many=True).data

    def get_cross_cutting_modifier(self, id):
        queryset = LGDCrossCuttingModifier.objects.filter(lgd_id=id)
        return LGDCrossCuttingModifierSerializer(queryset, many=True).data

    def get_publications(self, id):
        queryset = LGDPublication.objects.filter(lgd_id=id)
        return LGDPublicationSerializer(queryset, many=True).data

    def get_phenotypes(self, id):
        queryset = LGDPhenotype.objects.filter(lgd_id=id)
        return LGDPhenotypeSerializer(queryset, many=True).data

    def get_variant_type(self, id):
        queryset = LGDVariantType.objects.filter(lgd_id=id)
        return VariantTypeSerializer(queryset, many=True).data

    def get_panels(self, id):
        queryset = LGDPanel.objects.filter(lgd_id=id)
        return LGDPanelSerializer(queryset, many=True).data

    def get_comments(self, id):
        lgd_comments = LGDComment.objects.filter(lgd_id=id)
        data = []
        for comment in lgd_comments:
            text = { 'text':comment.comment,
                     'date':comment.date }
            data.append(text)

        return data

    # This method depends on the history table
    # Entries that were migrated from the old db don't have the date when they were created
    def get_date_created(self, id):
        date = None
        lgd_obj = self.instance
        insertion_history_type = '+'
        history_records = lgd_obj.history.all().order_by('history_date').filter(history_type=insertion_history_type)
        if history_records:
            date = history_records.first().history_date.date()

        return date

    class Meta:
        model = LocusGenotypeDisease
        exclude = ['id', 'is_deleted', 'date_review']
        read_only_fields = ['stable_id']

class VariantConsequenceSerializer(serializers.ModelSerializer):
    variant_consequence = serializers.CharField(source="variant_consequence.term")
    support = serializers.CharField(source="support.value")
    publication = serializers.CharField(source="publication.title", allow_null=True)

    class Meta:
        model = LGDVariantGenccConsequence
        fields = ['variant_consequence', 'support', 'publication']

class LGDMolecularMechanismSerializer(serializers.ModelSerializer):
    mechanism = serializers.CharField(source="mechanism.value")
    support = serializers.CharField(source="mechanism_support.value")
    description = serializers.CharField(source="mechanism_description", allow_null=True)
    synopsis = serializers.CharField(source="synopsis.value", allow_null=True)
    synopsis_support = serializers.CharField(source="synopsis_support.value", allow_null=True)
    publication = serializers.CharField(source="publication.title", allow_null=True)

    class Meta:
        model = LGDVariantGenccConsequence
        fields = ['mechanism', 'support', 'description', 'synopsis', 'synopsis_support', 'publication']

class LGDCrossCuttingModifierSerializer(serializers.ModelSerializer):
    term = serializers.CharField(source="ccm.value")

    class Meta:
        model = LGDCrossCuttingModifier
        fields = ['term']

class PublicationSerializer(serializers.ModelSerializer):
    pmid = serializers.CharField()
    title = serializers.CharField(read_only=True)
    authors = serializers.CharField(read_only=True)
    year = serializers.CharField(read_only=True)
    comments = serializers.SerializerMethodField()

    def get_comments(self, id):
        data = []
        comments = PublicationComment.objects.filter(publication=id)
        for comment in comments:
            text = { 'text':comment.comment,
                     'date':comment.date }
            data.append(text)

        return data

    def create(self, validated_data):
        pmid = validated_data.get('pmid')

        try:
            publication_obj = Publication.objects.get(pmid=pmid)
            raise serializers.ValidationError({"message": f"publication already exists",
                                                "please check publication":
                                                f"PMID: {pmid}, Title: {publication_obj.title}"})
        except Publication.DoesNotExist:
            response = get_publication(pmid)

            if response['hitCount'] == 0:
                raise serializers.ValidationError({"message": f"invalid pmid",
                                                   "please check id": pmid})

            authors = get_authors(response)
            year = None
            doi = None
            publication_info = response['result']
            title = publication_info['title']
            if 'doi' in publication_info:
                doi = publication_info['doi']
            if 'pubYear' in publication_info:
                year = publication_info['pubYear']

            # Insert publication
            publication_obj = Publication.objects.create(pmid = pmid,
                                                         title = title,
                                                         authors = authors,
                                                         year = year,
                                                         doi = doi)

        return publication_obj

    class Meta:
        model = Publication
        fields = ['pmid', 'title', 'authors', 'year', 'comments']

class LGDPublicationSerializer(serializers.ModelSerializer):
    publication = PublicationSerializer()

    class Meta:
        model = LGDPublication
        fields = ['publication']

class DiseasePublicationSerializer(serializers.ModelSerializer):
    pmid = serializers.CharField(source="publication.pmid")
    title = serializers.CharField(source="publication.title", allow_null=True)
    number_families = serializers.IntegerField(source="families", allow_null=True)
    consanguinity = serializers.CharField(allow_null=True)
    ethnicity = serializers.CharField(allow_null=True)

    class Meta:
        model = DiseasePublication
        fields = ['pmid', 'title', 'number_families', 'consanguinity', 'ethnicity']

class DiseaseOntologySerializer(serializers.ModelSerializer):
    accession = serializers.CharField(source="ontology_term.accession")
    term = serializers.CharField(source="ontology_term.term")
    description = serializers.CharField(source="ontology_term.description", allow_null=True)

    class Meta:
        model = DiseaseOntology
        fields = ['accession', 'term', 'description']

class DiseaseSerializer(serializers.ModelSerializer):
    name = serializers.CharField()
    mim = serializers.CharField()
    ontology_terms = serializers.SerializerMethodField()
    publications = serializers.SerializerMethodField()
    synonyms = serializers.SerializerMethodField()

    def get_ontology_terms(self, id):
        disease_ontologies = DiseaseOntology.objects.filter(disease=id)
        return DiseaseOntologySerializer(disease_ontologies, many=True).data

    def get_publications(self, id):
        disease_publications = DiseasePublication.objects.filter(disease=id)
        return DiseasePublicationSerializer(disease_publications, many=True).data

    def get_synonyms(self, id):
        synonyms = []
        disease_synonyms = DiseaseSynonym.objects.filter(disease=id)
        for d_synonym in disease_synonyms:
            synonyms.append(d_synonym.synonym)
        return synonyms

    class Meta:
        model = Disease
        fields = ['name', 'mim', 'ontology_terms', 'publications', 'synonyms']

class DiseaseDetailSerializer(DiseaseSerializer):
    last_updated = serializers.SerializerMethodField()

    def get_last_updated(self, id):
        dates = []
        lgds = LocusGenotypeDisease.objects.filter(disease=id)
        for lgd in lgds:
            if lgd.date_review is not None and lgd.is_reviewed == 1 and lgd.is_deleted == 0:
                dates.append(lgd.date_review)
                dates.sort()
        if len(dates) > 0:
            return dates[-1].date()
        else:
            return []

    class Meta:
        model = Disease
        fields = DiseaseSerializer.Meta.fields + ['last_updated']

class CreateDiseaseSerializer(serializers.ModelSerializer):
    ontology_terms = DiseaseOntologySerializer(required=False)
    publications = DiseasePublicationSerializer(required=False)

    @transaction.atomic
    def create(self, validated_data):
        disease_name = validated_data.get('name')
        mim = validated_data.get('mim')
        ontology = validated_data.get('ontology_terms')
        ontology_accession = ontology['ontology_term']['accession']
        ontology_term = ontology['ontology_term']['term']
        ontology_desc = ontology['ontology_term']['description']
        publications = validated_data.get('publications')
        publication_pmid = publications['publication']['pmid']
        publication_title = publications['publication']['title']
        n_families = publications['families']
        consanguinity = publications['consanguinity']
        ethnicity = publications['ethnicity']

        disease_obj = None

        # Clean disease name
        disease_name_clean = clean_string(str(disease_name))
        # Check if name already exists
        all_disease_names = Disease.objects.all()
        for disease_db in all_disease_names:
            disease_db_clean = clean_string(str(disease_db.name))
            if disease_db_clean == disease_name_clean:
                disease_obj = disease_db
        all_disease_synonyms = DiseaseSynonym.objects.all()
        for disease_synonym in all_disease_synonyms:
            disease_db_clean = clean_string(str(disease_synonym.synonym))
            if disease_db_clean == disease_name_clean:
                disease_obj = disease_synonym.disease

        if disease_obj is None:
            # TODO: check if MIM is valid - need OMIM API access
            # TODO: give disease suggestions

            disease_obj = Disease.objects.create(
                name = disease_name,
                mim = mim
            )

            # Check if ontology is in db
            if ontology_accession is not None and ontology_term is not None:
                try:
                    ontology_obj = OntologyTerm.objects.get(accession=ontology_accession)
                except OntologyTerm.DoesNotExist:
                    # Check if ontology accession is valid
                    mondo_disease = get_mondo(ontology_accession)
                    if mondo_disease is None:
                        raise serializers.ValidationError({"message": f"invalid mondo id",
                                                           "please check id": ontology_accession})

                    source = Source.objects.get(name="Mondo")

                    # Insert ontology
                    ontology_accession = re.sub(r'\_', ':', ontology_accession)
                    ontology_term = re.sub(r'\_', ':', ontology_term)
                    if ontology_desc is None and len(mondo_disease['description']) > 0:
                        ontology_desc = mondo_disease['description'][0]
                    ontology_obj = OntologyTerm.objects.create(
                        accession = ontology_accession,
                        term = ontology_term,
                        description = ontology_desc,
                        source = source
                    )

                # Insert disease ontology
                attrib = Attrib.objects.get(value="Data source")
                disease_ontology_obj = DiseaseOntology.objects.create(
                    disease = disease_obj,
                    ontology_term = ontology_obj,
                    mapped_by_attrib = attrib
                )

            # Insert disease publication info
            try:
                publication_obj = Publication.objects.get(pmid=publication_pmid)
            except Publication.DoesNotExist:
                publication = get_publication(publication_pmid)
                if publication['hitCount'] == 0:
                    raise serializers.ValidationError({"message": f"invalid pmid",
                                                                   "please check id": publication_pmid})

                # Insert publication
                if publication_title is None:
                    publication_title = publication['result']['title']
                publication_authors = get_authors(publication)
                publication_doi = publication['result']['doi']
                publication_year = publication['result']['pubYear']
                publication_obj = Publication.objects.create(
                    pmid = publication_pmid,
                    title = publication_title,
                    authors = publication_authors,
                    doi = publication_doi,
                    year = publication_year
                )

            # Insert disease_publication
            try:
                disease_publication_obj = DiseasePublication.objects.get(disease=disease_obj, publication=publication_obj)
            except DiseasePublication.DoesNotExist:
                disease_publication_obj = DiseasePublication.objects.create(
                    disease = disease_obj,
                    publication = publication_obj,
                    families = n_families,
                    consanguinity = consanguinity,
                    ethnicity = ethnicity,
                    is_deleted = 0
                )

        else:
            raise serializers.ValidationError({"message": f"disease already exists",
                                               "please select existing disease": disease_obj.name})

        return disease_obj

    class Meta:
        model = Disease
        fields = ['name', 'mim', 'ontology_terms', 'publications']

class PhenotypeSerializer(serializers.ModelSerializer):
    name = serializers.CharField(source="term", read_only=True)
    description = serializers.CharField(read_only=True)

    @transaction.atomic
    def create(self, validated_data):
        phenotype_accession = validated_data.get('accession')
        phenotype_description = None

        # Check if accession is valid
        pheno = validate_phenotype(phenotype_accession)

        if not re.match("HP\:\d+", phenotype_accession) or pheno is None:
            raise serializers.ValidationError({"message": f"invalid phenotype accession",
                                               "please check id": phenotype_accession})

        if pheno['details']['isObsolete'] == True:
            raise serializers.ValidationError({"message": f"phenotype accession is obsolete",
                                               "please check id": phenotype_accession})

        if 'definition' in pheno['details']:
            phenotype_description = pheno['details']['definition']

        source_obj = Source.objects.filter(name='HPO')
        pheno_obj = OntologyTerm.objects.create(accession=phenotype_accession,
                                                term=pheno['details']['name'],
                                                description=phenotype_description,
                                                source=source_obj.first())

        return pheno_obj

    class Meta:
        model = OntologyTerm
        fields = ['name', 'accession', 'description']

class LGDPhenotypeSerializer(serializers.ModelSerializer):
    name = serializers.CharField(source="phenotype.term")
    accession = serializers.CharField(source="phenotype.accession")

    class Meta:
        model = LGDPhenotype
        fields = ['name', 'accession']

class VariantTypeSerializer(serializers.ModelSerializer):
    term = serializers.CharField(source="variant_type_ot.term")
    accession = serializers.CharField(source="variant_type_ot.accession")

    class Meta:
        model = LGDVariantType
        fields = ['term', 'accession']
