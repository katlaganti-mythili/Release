# TODO - Application Name Mapping Enhancement

## Steps

### Phase 1: Core Matching Logic
- [ ] Step 1: Add fuzzy matching and `find_best_application_match()` to `jira_excel_validator.py`
- [ ] Step 2: Add `extract_all_application_names_from_excel()` and `generate_application_mapping()`

### Phase 2: State & Graph Updates
- [ ] Step 3: Update `state.py` - Add `application_mapping` and `root_folder` fields
- [ ] Step 4: Update `nodes.py` - Add `map_applications` node
- [ ] Step 5: Update `graph.py` - Add mapping node to workflow

### Phase 3: Report Enhancement
- [ ] Step 6: Update `report_service.py` - Add mapping summary to report

### Phase 4: CLI & UI (Deferred - works via existing interfaces)
- [ ] Step 7: Update `main.py` - Add root-folder scanning mode (optional enhancement)
- [ ] Step 8: Update `app.py` - Add UI support for root-folder mode (optional enhancement)

### Phase 5: Testing
- [ ] Step 9: Verify all syntax and imports - ✅ All files compile cleanly
- [ ] Step 10: Test the full flow with actual PDFs (requires company VPN / actual Release Notes PDFs)
