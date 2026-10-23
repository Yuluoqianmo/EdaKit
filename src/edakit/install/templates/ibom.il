; EdaKit Allegro iBOM entry. ASCII only for Cadence 17.2 startup parsing.
; axlRunBatchDBProgram uses a temporary snapshot, never overwrites the board.
edakitIBOMExe = "@EXE@"
edakitIBOMRoot = "@ROOT@"

procedure(edakitIBOMModelStem(name)
  let((size low)
    size = strlen(name)
    low = lowerCase(name)
    cond((size > 5 && substring(low size-4) == ".step" substring(name 1 size-5))
         (size > 4 && substring(low size-3) == ".stp" substring(name 1 size-4))
         (t name))
  )
)

procedure(edakitIBOMWriteLabels(path)
  let((fp mp scale side box mapping paths psm resolved cache entry facet stem packagePath facetPaths)
    fp = outfile(path)
    mp = outfile(strcat(path ".models.tsv"))
    scale = axlMKSConvert(1.0 car(axlDBGetDesignUnits()) "millimeters")
    paths = axlGetVariable("steppath")
    unless(stringp(paths) paths = "")
    psm = axlGetVariable("psmpath")
    when(stringp(psm) paths = strcat(paths " " psm))
    facetPaths = axlGetVariable("step_facet_path")
    when(stringp(facetPaths) paths = strcat(paths " " facetPaths))
    fprintf(mp "refdes\tfile\trx\try\trz\tox\toy\toz\tsearch\tresolved\tfacet_resolved\tpackage_resolved\n")
    fprintf(fp "refdes\tside\tminX\tminY\tmaxX\tmaxY\trotation\tmirrored\n")
    foreach(sym axlDBGetDesign()->symbols
      mapping = nil
      when(sym->component mapping = axlStepGet(nil 'primary sym->component->compdef))
      unless(mapping
        mapping = axlStepGet(nil 'primary sym->definition))
      unless(mapping mapping = axlStepGet(nil 'alt sym->definition))
      when(mapping
        entry = assoc(mapping->step_name cache)
        if(entry then
          resolved = cadr(entry)
          facet = caddr(entry)
        else
          resolved = axlDMFindFile("ALLEGRO_STEP" mapping->step_name "r")
          unless(resolved resolved = "")
          stem = edakitIBOMModelStem(mapping->step_name)
          facet = axlDMFindFile("ALLEGRO_STEP_FACET" stem "r")
          unless(facet facet = axlDMFindFile("ALLEGRO_STEP_FACET" strcat("stepFacetFiles4Map/" stem) "r"))
          unless(facet facet = "")
          cache = cons(list(mapping->step_name resolved facet) cache))
        packagePath = axlDMFindFile("ALLEGRO_PACKAGE_DB" sym->name "r")
        unless(packagePath packagePath = "")
        fprintf(mp "%s\t%s\t%.6f\t%.6f\t%.6f\t%.9f\t%.9f\t%.9f\t%s\t%s\t%s\t%s\n"
          sym->refdes mapping->step_name mapping->rotation_x mapping->rotation_y mapping->rotation_z
          mapping->offset_x*scale mapping->offset_y*scale mapping->offset_z*scale paths resolved facet packagePath))
      foreach(tx axlDBGetAttachedText(sym)
        side = cond((tx->layer == "REF DES/SILKSCREEN_TOP" "top")
                    (tx->layer == "REF DES/SILKSCREEN_BOTTOM" "bottom") (t nil))
        when(side && tx->text == sym->refdes
          box = tx->bBox
          fprintf(fp "%s\t%s\t%.9f\t%.9f\t%.9f\t%.9f\t%.6f\t%d\n"
            sym->refdes side
            xCoord(car(box))*scale yCoord(car(box))*scale
            xCoord(cadr(box))*scale yCoord(cadr(box))*scale
            tx->rotation if(tx->isMirrored then 1 else 0))
        )
      )
    )
    close(fp)
    close(mp)
    path
  )
)

procedure(edakitIBOMArg(text)
  let((out ch i)
    out = ""
    for(i 1 strlen(text)
      ch = substring(text i 1)
      out = strcat(out cond((ch == "%" "%%") (ch == "\\" "/") (t ch)))
    )
    sprintf(nil "\"%s\"" out)
  )
)

procedure(edakitIBOMRun(mode)
  let((cmd result source labels)
    source = axlGetDrawingName()
    if(mode == "export" then
      if(!axlDBGetDesign() || axlIsSymbolEditor() then
        axlUIConfirm("Open a PCB board before exporting iBOM.")
        nil
      else
        labels = edakitIBOMWriteLabels(axlTempFile())
        cmd = strcat(edakitIBOMArg(edakitIBOMExe)
          " ibom-export --board %s --source " edakitIBOMArg(source)
          " --cadence-root " edakitIBOMArg(edakitIBOMRoot)
          " --labels " edakitIBOMArg(labels) " --dialog --notify")
        result = axlRunBatchDBProgram(edakitIBOMExe cmd
          ?reloadDB nil ?startMsg "EdaKit interactive BOM export")
        axlTempFileRemove(labels)
        deleteFile(strcat(labels ".models.tsv"))
        when(result == t axlUIWPrint(nil "EdaKit iBOM window opened."))
        result
      )
    else
      cmd = strcat(edakitIBOMArg(edakitIBOMExe) " ibom-settings --source "
        edakitIBOMArg(source) " --detach --notify " mode)
      axlRunBatchDBProgram(edakitIBOMExe cmd ?noUnload t ?noProgress t)
    )
  )
)
procedure(edakitIBOMExport() edakitIBOMRun("export"))
procedure(edakitIBOMFolder() edakitIBOMRun("--pick-folder"))
procedure(edakitIBOMChooseBOM() edakitIBOMRun("--choose-bom"))
procedure(edakitIBOMPCBProperties() edakitIBOMRun("--clear-bom"))
axlCmdRegister("edakit_ibom" 'edakitIBOMExport ?cmdType "general")
axlCmdRegister("edakit_ibom_folder" 'edakitIBOMFolder ?cmdType "general")
axlCmdRegister("edakit_ibom_bom" 'edakitIBOMChooseBOM ?cmdType "general")
axlCmdRegister("edakit_ibom_pcb" 'edakitIBOMPCBProperties ?cmdType "general")
unless(boundp('edakitIBOMMenuRegistered) && edakitIBOMMenuRegistered
  edakitIBOMMenuRegistered = axlUIMenuRegister(-1
    '((popup "EdaKit")
      ("Interactive BOM..." "edakit_ibom")))
)
