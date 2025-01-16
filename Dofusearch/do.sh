#!/bin/bash

# Define the languages to fetch data for
languages=("en" "fr" "es" "pt" "de")

# Create or clear the output file
output_file="mount_family_names.txt"
> "$output_file"

# Loop over each language
for lang in "${languages[@]}"; do
  echo "Fetching data for language: $lang"
  
  # Fetch the data and filter the family names
  curl -X 'GET' \
    "https://api.dofusdu.de/dofus3/v1/$lang/mounts/all" \
    -H 'accept: application/json' | \
    jq -r '.mounts[].family.name' | \
    sort | \
    uniq > "$lang_families.txt"

  # Append the language and its family names to the final output file
  echo "Language: $lang" >> "$output_file"
  cat "$lang_families.txt" >> "$output_file"
  echo -e "\n" >> "$output_file"
  
  # Clean up temporary file for the language
  rm "$lang_families.txt"
done

echo "Finished saving unique family names to $output_file"
