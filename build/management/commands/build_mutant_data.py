from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
from django.db import connection
from django.utils.text import slugify

from mutation.models import *

from common.views import AbsTargetSelection
from common.views import AbsSegmentSelection

from residue.models import Residue
from protein.models import Protein
from ligand.models import Ligand, LigandProperities, LigandRole
from common.models import WebLink, WebResource, Publication

from datetime import datetime
from collections import OrderedDict
import json
from urllib.request import urlopen, quote
#env/bin/python3 -m pip install xlrd

import re
import math
import xlrd

from optparse import make_option
import logging, os, re
import yaml


## FOR VIGNIR ORDERED DICT YAML IMPORT/DUMP
_mapping_tag = yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG
def dict_constructor(loader, node):
    return OrderedDict(loader.construct_pairs(node))

def represent_ordereddict(dumper, data):
    value = []

    for item_key, item_value in data.items():
        node_key = dumper.represent_data(item_key)
        node_value = dumper.represent_data(item_value)

        value.append((node_key, node_value))

    return yaml.nodes.MappingNode(u'tag:yaml.org,2002:map', value)

yaml.add_representer(OrderedDict, represent_ordereddict)
yaml.add_constructor(_mapping_tag, dict_constructor)

class Command(BaseCommand):
    help = 'Reads source data and creates pdb structure records'
    
    def add_arguments(self, parser):
        parser.add_argument('--filename', action='append', dest='filename',
            help='Filename to import. Can be used multiple times')
        parser.add_argument('--purge', action='store_true', dest='purge', default=False,
            help='Purge existing mutations records')

    logger = logging.getLogger(__name__)

    # source file directory
    structure_data_dir = os.sep.join([settings.DATA_DIR, 'mutant_data', 'xls'])

    def handle(self, *args, **options):
        # delete any existing structure data
        if options['purge']:
            try:
                self.truncate_structure_tables()
            except Exception as msg:
                print(msg)
                self.logger.error(msg)
        # import the structure data
        try:
            self.create_mutant_data(options['filename'])
        except Exception as msg:
            print(msg)
            self.logger.error(msg)
    
    def truncate_structure_tables(self):
        cursor = connection.cursor()
        
        tables_to_truncate = [
            #Following the changes in the models - SM
            'mutation_experiment',                
        ]

        for table in tables_to_truncate:
            cursor.execute("TRUNCATE TABLE {!s} CASCADE".format(table))

    def loaddatafromexcel(self,excelpath):
        workbook = xlrd.open_workbook(excelpath)
        worksheets = workbook.sheet_names()
        temp = []
        for worksheet_name in worksheets:
            worksheet = workbook.sheet_by_name(worksheet_name)
            #print(worksheet_name)

            if worksheet.cell_value(0, 0) == "REFERENCE \nDOI (or PMID)":
                #print("MATCH")
                pass
            else:
                #print("SKIPPING")
                continue

            num_rows = worksheet.nrows - 1
            num_cells = worksheet.ncols - 1
            curr_row = 0 #skip first, otherwise -1
            while curr_row < num_rows:
                curr_row += 1
                row = worksheet.row(curr_row)
                #print('Row:', curr_row)
                curr_cell = -1
                temprow = []
                if worksheet.cell_value(curr_row, 0) == '': #if empty
                    continue
                while curr_cell < num_cells:
                    curr_cell += 1
                    # Cell Types: 0=Empty, 1=Text, 2=Number, 3=Date, 4=Boolean, 5=Error, 6=Blank
                    cell_type = worksheet.cell_type(curr_row, curr_cell)
                    cell_value = worksheet.cell_value(curr_row, curr_cell)
                    #print('    ', cell_type, ':', cell_value)
                    temprow.append(cell_value)
                temp.append(temprow)
                #if curr_row>10: break
            return temp

    def analyse_rows(self,rows):
        temp = []
        for r in rows:
            d = {}
            d['reference'] = r[0]
            d['protein'] = r[1].replace("__","_").lower()
            d['mutation_pos'] = r[2]
            d['mutation_from'] = r[3]
            d['mutation_to'] = r[4]
            d['ligand_name'] = r[5]
            d['ligand_type'] = r[6]
            d['ligand_id'] = r[7]
            d['ligand_class'] = r[8]
            d['exp_type'] = r[9]
            d['exp_func'] = r[10]
            d['exp_wt_value'] = int(r[11]) if r[11] else 0
            d['exp_wt_unit'] = r[12]
            d['exp_mu_effect_type'] = r[13]
            d['exp_mu_effect_sign'] = r[14]
            d['exp_mu_value_raw'] = int(r[15]) if r[15] else 0
            d['exp_mu_effect_qual'] = r[16]
            d['exp_mu_effect_ligand_prop'] = r[17]
            d['exp_mu_ligand_ref'] = r[18]
            d['opt_type'] = r[21]
            d['opt_wt'] = int(r[22]) if r[22] else 0
            d['opt_mu'] = int(r[23]) if r[23] else 0
            d['opt_sign'] = r[24]
            d['opt_percentage'] = int(r[25]) if r[25] else 0
            d['opt_qual'] = r[26]
            d['opt_agonist'] = r[27]



            if isinstance(d['ligand_id'], float): d['ligand_id'] = int(d['ligand_id'])
            if isinstance(d['mutation_pos'], float): d['mutation_pos'] = int(d['mutation_pos'])


            temp.append(d)
        return temp


    def insert_raw(self,r):
        obj, created = MutationRaw.objects.get_or_create(
        reference=r['reference'], 
        protein=r['protein'], 
        mutation_pos=r['mutation_pos'], 
        mutation_from=r['mutation_from'], 
        mutation_to=r['mutation_to'], 
        ligand_name=r['ligand_name'], 
        ligand_idtype=r['ligand_type'], 
        ligand_id=r['ligand_id'], 
        ligand_class=r['ligand_class'], 
        exp_type=r['exp_type'], 
        exp_func=r['exp_func'], 
        exp_wt_value=r['exp_wt_value'], #
        exp_wt_unit=r['exp_wt_unit'], 
        exp_mu_effect_type=r['exp_mu_effect_type'], 
        exp_mu_effect_sign=r['exp_mu_effect_sign'], 
        exp_mu_effect_value=r['exp_mu_value_raw'], #
        exp_mu_effect_qual=r['exp_mu_effect_qual'], 
        exp_mu_effect_ligand_prop=r['exp_mu_effect_ligand_prop'], 
        exp_mu_ligand_ref=r['exp_mu_ligand_ref'], 
        opt_type=r['opt_type'], 
        opt_wt=r['opt_wt'], #
        opt_mu=r['opt_mu'], #
        opt_sign=r['opt_sign'], 
        opt_percentage=r['opt_percentage'], #
        opt_qual=r['opt_qual'], 
        opt_agonist=r['opt_agonist'], 
        added_by='munk', 
        added_date=datetime.now()
        )

        raw_id = obj

        return raw_id



    def create_mutant_data(self, filenames):
        self.logger.info('CREATING MUTANT DATA')
        
        # what files should be parsed?
        if not filenames:
            filenames = os.listdir(self.structure_data_dir)

        for source_file in filenames:
            source_file_path = os.sep.join([self.structure_data_dir, source_file])
            if os.path.isfile(source_file_path) and source_file[0] != '.':
                self.logger.info('Reading file {}'.format(source_file_path))
                print("Reading "+source_file_path)
                # read the yaml file
                rows = self.loaddatafromexcel(source_file_path)
                rows = self.analyse_rows(rows)

                c = 0
                skipped = 0
                inserted = 0
                for r in rows:
                    print("Inserted",inserted,"Skipped",skipped)
                    #print(r)
                    raw_experiment = self.insert_raw(r)

                    # publication
                    try:
                        pub = Publication.objects.get(web_link__index=r['reference'])
                    except Publication.DoesNotExist as e:
                        pub = Publication()
                        try:
                            pub.web_link = WebLink.objects.get(index=r['reference'], web_resource__slug='doi')
                        except WebLink.DoesNotExist:
                            wl = WebLink.objects.create(index=r['reference'],
                                web_resource = WebResource.objects.get(slug='doi'))
                            pub.web_link = wl
                        pub.update_from_doi(doi=r['reference'])
                        pub.save()

                    if r['ligand_type']=='PubChem CID':
                        print('inserting by pubchem id')
                        try:
                            web_resource = WebResource.objects.get(slug='pubchem')
                        except:
                            # abort if pdb resource is not found
                            raise Exception('PubChem resource not found, aborting!')

                        test = LigandProperities.objects.filter(web_links__web_resource=web_resource, web_links__index=r['ligand_id'])
                        if Ligand.objects.filter(name=r['ligand_name'], properities__web_links__web_resource=web_resource, properities__web_links__index=r['ligand_id']).exists(): #if this name is canonical and it has a ligand record already
                            l = Ligand.objects.get(name=r['ligand_name'], properities__web_links__web_resource=web_resource, properities__web_links__index=r['ligand_id'])
                            print('found by pubchem id')
                        elif Ligand.objects.filter(properities__web_links__web_resource=web_resource, properities__web_links__index=r['ligand_id'], canonical=True).exists(): #if exists under different name
                            l_canonical = Ligand.objects.get(properities__web_links__web_resource=web_resource, properities__web_links__index=r['ligand_id'], canonical=True)
                            l = Ligand()
                            l.properities = l_canonical.properities
                            l.name = str(r['ligand_name'])
                            l.canonical = False
                            l.save()
                            print('found by pubchem id, added alias')
                        else:
                            print('pubchem id not found, adding',r['ligand_id'])
                            pubchem_url = 'https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/' + str(r['ligand_id']) + '/property/CanonicalSMILES,InChIKey/json'
                            print(pubchem_url)
                            try:
                                req = urlopen(pubchem_url)
                                pubchem = json.loads(req.read().decode('UTF-8'))

                                pubchem_smiles = pubchem['PropertyTable']['Properties'][0]['CanonicalSMILES']
                                pubchem_inchikey = pubchem['PropertyTable']['Properties'][0]['InChIKey']

                                if Ligand.objects.filter(name=r['ligand_name'], properities__inchikey=pubchem_inchikey).exists(): #if this name is canonical and it has a ligand record already
                                    l = Ligand.objects.get(name=r['ligand_name'], properities__inchikey=pubchem_inchikey)
                                    wl, created = WebLink.objects.get_or_create(index=r['ligand_id'], web_resource=web_resource)
                                    l.properities.web_links.add(wl)
                                elif Ligand.objects.filter(properities__inchikey=pubchem_inchikey, canonical=True).exists(): #if exists under different name
                                    l_canonical = Ligand.objects.get(properities__inchikey=pubchem_inchikey, canonical=True)
                                    l = Ligand()
                                    l.properities = l_canonical.properities
                                    wl, created = WebLink.objects.get_or_create(index=r['ligand_id'], web_resource=web_resource)
                                    l.properities.web_links.add(wl)
                                    l.name = str(r['ligand_name'])
                                    l.canonical = False
                                    l.save()
                                else: #if neither found by pubchem id or inchi key, create new
                                    lp = LigandProperities()
                                    lp.inchikey = pubchem_inchikey
                                    lp.smiles = pubchem_smiles
                                    lp.save()
                                    wl, created = WebLink.objects.get_or_create(index=r['ligand_id'], web_resource=web_resource)
                                    lp.web_links.add(wl)
                                    l = Ligand()
                                    l.properities = lp
                                    l.name = str(r['ligand_name'])
                                    l.canonical = True
                                    l.ambigious_alias = False
                                    l.save()
                                    l.load_by_name(str(r['ligand_name']))
                            except:
                                raise Exception('JSON failed, aborting!')
                        
                    elif r['ligand_type']=='SMILES':
                        print('inserting by smiles')

                        if Ligand.objects.filter(name=r['ligand_name'], properities__smiles=r['ligand_id']).exists(): #if this name is canonical and it has a ligand record already
                            l = Ligand.objects.get(name=r['ligand_name'], properities__smiles=r['ligand_id'])
                        elif Ligand.objects.filter(properities__smiles=r['ligand_id'], canonical=True).exists(): #if exists under different name
                            l_canonical = Ligand.objects.get(properities__smiles=r['ligand_id'], canonical=True)
                            l = Ligand()
                            l.properities = l_canonical.properities
                            l.name = str(r['ligand_name'])
                            l.canonical = False
                            l.save()
                        else: #if neither found by SMILES

                            pubchem_url = 'https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/smiles/' + str(r['ligand_id']) + '/property/CanonicalSMILES,InChIKey/json'
                            print(pubchem_url)
                            try:
                                req = urlopen(pubchem_url)
                                pubchem = json.loads(req.read().decode('UTF-8'))

                                pubchem_smiles = pubchem['PropertyTable']['Properties'][0]['CanonicalSMILES']
                                pubchem_inchikey = pubchem['PropertyTable']['Properties'][0]['InChIKey']

                                lp = LigandProperities()
                                lp.inchikey = pubchem_inchikey
                                lp.smiles = pubchem_smiles
                                lp.save()
                                l = Ligand()
                                l.properities = lp
                                l.name = str(r['ligand_name'])
                                l.canonical = True
                                l.ambigious_alias = False
                                l.save()
                                l.load_by_name(str(r['ligand_name']))
                            except:
                                #raise Exception('JSON failed, aborting!')
                                print('Inserting '+str(r['ligand_name']))
                                lp = LigandProperities()
                                lp.smiles = str(r['ligand_id'])
                                lp.save()
                                l = Ligand()
                                l.properities = lp
                                l.name = str(r['ligand_name'])
                                l.canonical = True
                                l.ambigious_alias = False
                                l.save()
                                #l.load_by_name(str(r['ligand_name']))
                    else:
                        print('inserting by something else',r['ligand_type'],r['ligand_name'],r['ligand_id'])
                        if Ligand.objects.filter(name=r['ligand_name'], canonical=True).exists(): #if this name is canonical and it has a ligand record already
                            l = Ligand.objects.get(name=r['ligand_name'], canonical=True)
                        elif Ligand.objects.filter(name=r['ligand_name'], canonical=False, ambigious_alias=False).exists(): #if this matches an alias that only has "one" parent canonical name - eg distinct
                            l = Ligand.objects.get(name=r['ligand_name'], canonical=False, ambigious_alias=False)
                        elif Ligand.objects.filter(name=r['ligand_name'], canonical=False, ambigious_alias=True).exists(): #if this matches an alias that only has several canonical parents, must investigate, start with empty.
                            #print('Inserting '+ligand['name']+" for "+sd['pdb'])
                            lp = LigandProperities()
                            lp.save()
                            l = Ligand()
                            l.properities = lp
                            l.name = r['ligand_name']
                            l.canonical = False
                            l.ambigious_alias = True
                            l.save()
                            l.load_by_name(r['ligand_name'])
                        else: #if niether a canonical or alias exists, create the records. Remember to check for canonical / alias status.
                            print('Inserting '+str(r['ligand_name']))
                            lp = LigandProperities()
                            lp.save()
                            l = Ligand()
                            l.properities = lp
                            l.name = str(r['ligand_name'])
                            l.canonical = True
                            l.ambigious_alias = False
                            l.save()
                            l.load_by_name(str(r['ligand_name']))
                    l.save()

                    if Ligand.objects.filter(name=r['exp_mu_ligand_ref'], canonical=True).exists(): #if this name is canonical and it has a ligand record already
                        l_ref = Ligand.objects.get(name=r['exp_mu_ligand_ref'], canonical=True)
                    elif Ligand.objects.filter(name=r['exp_mu_ligand_ref'], canonical=False, ambigious_alias=False).exists(): #if this matches an alias that only has "one" parent canonical name - eg distinct
                        l_ref = Ligand.objects.get(name=r['exp_mu_ligand_ref'], canonical=False, ambigious_alias=False)
                    elif Ligand.objects.filter(name=r['exp_mu_ligand_ref'], canonical=False, ambigious_alias=True).exists(): #if this matches an alias that only has several canonical parents, must investigate, start with empty.
                        #print('Inserting '+ligand['name']+" for "+sd['pdb'])
                        lp = LigandProperities()
                        lp.save()
                        l_ref = Ligand()
                        l_ref.properities = lp
                        l_ref.name = r['exp_mu_ligand_ref']
                        l_ref.canonical = False
                        l_ref.ambigious_alias = True
                        l_ref.save()
                        l_ref.load_by_name(r['exp_mu_ligand_ref'])
                    else: #if niether a canonical or alias exists, create the records. Remember to check for canonical / alias status.
                        print('Inserting ref '+str(r['exp_mu_ligand_ref']))
                        lp = LigandProperities()
                        lp.save()
                        l_ref = Ligand()
                        l_ref.properities = lp
                        l_ref.name = r['exp_mu_ligand_ref']
                        l_ref.canonical = True
                        l_ref.ambigious_alias = False
                        l_ref.save()
                        l_ref.load_by_name(r['exp_mu_ligand_ref'])
                    l_ref.save()

                    protein_id = 0
                    residue_id = 0

                    protein=Protein.objects.filter(entry_name=r['protein'])
                    if protein.exists():
                        protein=protein.get()
                    else:
                        whattoreturn.append(['Skipped due to no protein',r['protein']])
                        skipped += 1
                        continue

                    res=Residue.objects.filter(protein_conformation__protein=protein,sequence_number=r['mutation_pos'])
                    if res.exists():
                        res=res.get()
                    else:
                        whattoreturn.append(['Skipped due to no residue',r['protein'],r['mutation_pos']])
                        skipped += 1
                        continue

                    l_role, created = LigandRole.objects.get_or_create(name=r['ligand_class'])

                    #obj, created = MutationLigandRef.objects.get_or_create(reference=r['exp_mu_ligand_ref'])
                    #ligref_id = obj

                    exp_type_id, created = MutationExperimentalType.objects.get_or_create(type=r['exp_type'])

                    exp_func_id, created = MutationFunc.objects.get_or_create(func=r['exp_func'])

                    exp_measure_id, created = MutationMeasure.objects.get_or_create(measure=r['exp_mu_effect_type'])

                    exp_qual_id, created = MutationQual.objects.get_or_create(qual=r['exp_mu_effect_qual'], prop=r['exp_mu_effect_ligand_prop'])

                    #obj, created = MutationLigandRef.objects.get_or_create(reference=r['exp_mu_ligand_ref'])
                    #effect_ligand_reference_id = obj

                    exp_opt_id, created =  MutationOptional.objects.get_or_create(type=r['opt_type'], wt=r['opt_wt'], mu=r['opt_mu'], sign=r['opt_sign'], percentage=r['opt_percentage'], qual=r['opt_qual'], agonist=r['opt_agonist'])

                    mutation, created =  Mutation.objects.get_or_create(amino_acid=r['mutation_to'],protein=protein, residue=res)

                    
                    logtypes = ['pEC50','pIC50','pK']
                    
                    
                    foldchange = 0
                    typefold = ''
                    if r['exp_mu_effect_type']=='Activity/affinity' and r['exp_wt_value']!=0:
                                
                        if re.match("(" + ")|(".join(logtypes) + ")", r['exp_type']):  #-log values!
                            foldchange = round(math.pow(10,-r['exp_mu_value_raw'])/pow(10,-r['exp_wt_value']),3);
                            typefold = r['exp_type']+"_log"
                        else:
                            foldchange = round(r['exp_mu_value_raw']/r['exp_wt_value'],3);
                            typefold = r['exp_type']+"_not_log"
                        
                        
                        if foldchange<1 and foldchange!=0:
                            foldchange = -round((1/foldchange),3)
                        elif r['exp_mu_effect_type'] =='Fold effect (mut/wt)':
                            foldchange = round(r['exp_mu_value_raw'],3);
                            if foldchange<1: foldchange = -round((1/foldchange),3);
                    

                    obj, created = MutationExperiment.objects.get_or_create(
                    refs=pub, 
                    protein=protein, 
                    residue=res, #MISSING 
                    ligand=l, 
                    ligand_role=l_role, 
                    ligand_ref = l_ref,
                    raw = raw_experiment,
                    optional = exp_opt_id,
                    exp_type=exp_type_id, 
                    exp_func=exp_func_id, 
                    exp_measure = exp_measure_id,
                    exp_qual = exp_qual_id,

                    mutation=mutation, 
                    wt_value=r['exp_wt_value'], #
                    wt_unit=r['exp_wt_unit'], 

                    mu_value = r['exp_mu_value_raw'],
                    mu_sign = r['exp_mu_effect_sign'], 
                    foldchange = foldchange
                    #foldchange = 1

                    #added_by='munk', 
                    #added_date=datetime.now()
                    )
                    #print(foldchange)
                    mut_id = obj.id
                    print('added with id',mut_id)

                    #whattoreturn.append([protein_id,residue_id,raw_id,ref_id,lig_id,ligclass_id,exp_type_id,exp_func_id,exp_measure_id,exp_qual_id,typefold,foldchange,mut_id])
                    inserted += 1
                    c += 1



        self.logger.info('COMPLETED CREATING MUTANTS')