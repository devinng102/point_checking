*Run checking & export excel (remember to change excel version):*
   python export_checking_results.py .\point_name_16-9-2026_v1.csv --remarks-from .\point_name_checked_v4.xlsx -o .\point_name_checked_v5.xlsx

*Search Null equipment code in MongoDB*
   {$or:[
   { "Equipment Code": { $exists: false },
   "Function or Status Code": /FSALM/
   },{"Equipment Code": null,
   "Function or Status Code": /FSALM/}]
   }
