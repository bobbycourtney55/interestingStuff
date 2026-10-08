#!/bin/bash
# stream indiv26.zip, keep rows whose CMTE_ID is a 2026 Dem House/Senate principal/authorized committee
D=$1
unzip -p $D/indiv26.zip itcont.txt | awk -F'|' 'NR==FNR{split($0,a,",");m[a[1]]=a[2];next} ($1 in m){print m[$1]"|"$0}' $D/dem_cmtes.csv - > $D/dem_indiv.txt
wc -l $D/dem_indiv.txt
