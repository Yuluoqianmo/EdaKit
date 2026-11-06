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

; Read only, called on explicit export invocation, never during startup.
procedure(edakitDeliveryWriteFilms(path)
  let((fp artwork film group classes)
    fp = outfile(path)
    when(fp
      fprintf(fp "EDAKIT_FILMS\t1\n")
      artwork = axlGetParam("artwork")
      when(artwork
        foreach(name artwork->groupMembers
          film = axlGetParam(strcat("artwork:" name))
          unless(film error("Cannot read artwork record %s" name))
          fprintf(fp "F\t%s\t%d\t%d\n" name
            if(film->negative then 1 else 0) if(film->mirrored then 1 else 0))
          foreach(layer film->groupMembers fprintf(fp "L\t%s\t%s\n" name layer))
        )
      )
      classes = axlGetParam("paramLayerGroup")
      unless(classes error("Cannot read PCB layer classes"))
      foreach(class classes->groupMembers
        group = axlGetParam(strcat("paramLayerGroup:" class))
        when(group
          foreach(subclass group->groupMembers fprintf(fp "K\t%s/%s\n" class subclass))
        )
      )
      group = axlGetParam("paramLayerGroup:ETCH")
      when(group
        foreach(subclass group->groupMembers
          fprintf(fp "P\t%s\t%d\n" subclass if(axlIsLayerNegative(strcat("ETCH/" subclass)) then 1 else 0))))
      fprintf(fp "END\t%d\n" if(artwork then length(artwork->groupMembers) else 0))
      close(fp)
    )
  )
)

; Explicit per-click bridge. No background callbacks and no startup DB access.
; A newer delivery window invalidates the previous window's session.
edakitFilmSession = nil
edakitFilmSource = nil
edakitFilmBusy = nil
edakitFilmBackup = nil
edakitFilmMutated = nil

procedure(edakitFilmProp(props key fallback)
  let((value found)
    while(props
      when(car(props) == key value = cadr(props) found = t)
      props = cddr(props))
    if(found then value else fallback)))

procedure(edakitFilmSpecs()
  let((group record result)
    group = axlGetParam("artwork")
    when(group
      foreach(name group->groupMembers
        record = axlGetParam(strcat("artwork:" name))
        unless(record error("Cannot read Film %s" name))
        result = cons(append(list(name if(record->negative then "1" else "0")
          if(record->mirrored then "1" else "0") name) copy(record->groupMembers)) result)))
    result))

procedure(edakitFilmSignature(specs)
  let((result)
    foreach(spec specs
      result = cons(append(list(car(spec) cadr(spec) caddr(spec))
        sort(copy(cddddr(spec)) 'alphalessp)) result))
    sort(result lambda((a b) alphalessp(car(a) car(b))))))

; Capture all supported Film settings, not just the three edited in the tree.
; Refuse unfamiliar nonempty properties rather than silently resetting them.
procedure(edakitFilmArgs(name props)
  let((args offset mapping key rest)
    mapping = '((negative ?negative) (undefineLineWidth ?undefineLineWidth)
      (sequence ?sequence) (rotation ?rotation) (shapeBoundingBox ?shapeBoundingBox)
      (mirrored ?mirrored) (fullContact ?fullContact)
      (suppressUnconnectPads ?suppressUnconnectPads)
      (drawMissingPadApertures ?drawMissingPadApertures)
      (useApertureRotation ?useApertureRotation) (suppressShapeFill ?suppressShapeFill)
      (vectorBasedPad ?vectorBasedPad) (drawHolesOnly ?drawHolesOnly)
      (domains ?domains) (ipc2581 ?ipc2581))
    args = list(name '?layers copy(edakitFilmProp(props 'groupMembers nil)))
    rest = props
    while(rest
      key = car(rest)
      cond((assoc(key mapping)
        args = append(args list(cadr(assoc(key mapping)) cadr(rest))))
        (member(key '(objType name groupMembers offset)) nil)
        (cadr(rest) error("Unsupported Film property %L in %s; no Film changed" key name)))
      rest = cddr(rest))
    offset = edakitFilmProp(props 'offset '(0.0 0.0))
    append(args list('?xOffset car(offset) '?yOffset cadr(offset)))))

procedure(edakitFilmCheckProps(name props edited)
  let((record current key)
    record = axlGetParam(strcat("artwork:" name))
    unless(record error("Film missing during property verification"))
    current = record->??
    while(props
      key = car(props)
      unless(member(key if(edited then '(objType name groupMembers negative mirrored) else '(objType)))
        unless(equal(cadr(props) edakitFilmProp(current key 'edakitMissingProperty))
          error("Film property readback changed: %s %L" name key)))
      props = cddr(props))
    t))

procedure(edakitFilmReadRequest(nonce)
  let((fp line rows row baseline target copper ended)
    fp = infile(strcat(edakitFilmSession ".request"))
    unless(fp error("Film request is missing"))
    while(gets(line fp) rows = cons(parseString(line "\t\r\n") rows))
    close(fp)
    rows = reverse(rows)
    unless(equal(car(rows) list("EDAKIT_FILM_APPLY" "1" nonce)) error("Stale Film session"))
    foreach(row cdr(rows)
      when(ended error("Unexpected data after Film END"))
      cond((car(row) == "C"
              unless(length(row) == 3 && member(caddr(row) '("0" "1")) error("Invalid copper record"))
              copper = cons(cdr(row) copper))
           (car(row) == "B" baseline = cons(cdr(row) baseline))
           (car(row) == "F" target = cons(cdr(row) target))
           (car(row) == "END"
             unless(equal(row list("END" sprintf(nil "%d" length(baseline))
               sprintf(nil "%d" length(target)))) error("Incomplete Film request"))
             ended = t)
           (t error("Unknown Film request record"))))
    unless(ended && target && copper error("Film request is incomplete or empty"))
    list(reverse(baseline) reverse(target) reverse(copper))))

procedure(edakitFilmRestore()
  let((group)
    group = axlGetParam("artwork")
    when(group
      foreach(name copy(group->groupMembers)
        axlDeleteObject(axlGetParam(strcat("artwork:" name)))))
    foreach(entry edakitFilmBackup
      unless(apply('axlFilmCreate cadr(entry)) error("Film rollback failed: %s" car(entry)))
      edakitFilmCheckProps(car(entry) cadddr(entry) nil))
    unless(equal(edakitFilmSignature(edakitFilmSpecs())
      edakitFilmSignature(mapcar('caddr edakitFilmBackup))) error("Film rollback verification failed"))
    t))

procedure(edakitFilmApplyRequest(nonce)
  let((request baseline target live names origins record props args old unchanged fp cmd result group)
    unless(edakitFilmSession && edakitFilmSource == axlGetDrawingName() && axlDBGetDesign()
      error("PCB/session changed; reopen EdaKit from current PCB"))
    request = edakitFilmReadRequest(nonce)
    baseline = car(request) target = cadr(request)
    group = axlGetParam("paramLayerGroup:ETCH")
    unless(group && equal(sort(copy(group->groupMembers) 'alphalessp)
      sort(mapcar('car caddr(request)) 'alphalessp))
      error("PCB copper stack changed; reopen delivery window"))
    foreach(layer caddr(request)
      unless(cadr(layer) == if(axlIsLayerNegative(strcat("ETCH/" car(layer))) then "1" else "0")
        error("PCB copper polarity changed; reopen delivery window")))
    live = edakitFilmSpecs()
    unless(equal(edakitFilmSignature(baseline) edakitFilmSignature(live))
      error("PCB Film changed since opening EdaKit; reopen delivery window"))
    foreach(spec target
      unless(length(spec) >= 5 && member(cadr(spec) '("0" "1")) && member(caddr(spec) '("0" "1"))
        error("Invalid Film specification"))
      when(member(lowerCase(car(spec)) names) error("Duplicate Film name"))
      names = cons(lowerCase(car(spec)) names)
      unless(cadddr(spec) == "*" || assoc(cadddr(spec) live) error("Unknown original Film"))
      when(cadddr(spec) == "*" && assoc(car(spec) live)
        error("Existing Film must preserve its original settings"))
      unless(cadddr(spec) == "*"
        when(member(cadddr(spec) origins) error("Original Film used twice"))
        origins = cons(cadddr(spec) origins))
      foreach(layer cddddr(spec)
        unless(axlIsLayer(layer) error("PCB layer does not exist: %s" layer))))
    ; Validate restoration arguments for every existing record before any write.
    foreach(spec live
      record = axlGetParam(strcat("artwork:" car(spec)))
      props = copy(record->??)
      args = edakitFilmArgs(car(spec) props)
      edakitFilmBackup = cons(list(car(spec) args spec props) edakitFilmBackup))
    fp = outfile(strcat(edakitFilmSession "." nonce ".backup.txt"))
    unless(fp error("Cannot write Film backup"))
    foreach(entry edakitFilmBackup fprintf(fp "%L\n" list(car(entry) cadddr(entry))))
    close(fp)
    foreach(spec target
      old = assoc(cadddr(spec) edakitFilmBackup)
      unchanged = old && car(spec) == car(old) &&
        equal(edakitFilmSignature(list(spec)) edakitFilmSignature(list(caddr(old))))
      unless(unchanged
        props = if(old then copy(cadddr(old)) else nil)
        ; Remove replaced fields from captured properties before adding edits.
        args = edakitFilmArgs(car(spec) props)
        args = cdr(args)
        result = nil
        while(args
          unless(member(car(args) '(?layers ?negative ?mirrored))
            result = append(result list(car(args) cadr(args))))
          args = cddr(args))
        args = append(list(car(spec) '?layers cddddr(spec)
          '?negative cadr(spec) == "1" '?mirrored caddr(spec) == "1") result)
        edakitFilmMutated = t
        unless(apply('axlFilmCreate args) error("Cannot create Film %s" car(spec)))
        when(old edakitFilmCheckProps(car(spec) props t))))
    foreach(spec live
      unless(assoc(car(spec) target)
        edakitFilmMutated = t
        axlDeleteObject(axlGetParam(strcat("artwork:" car(spec))))))
    unless(equal(edakitFilmSignature(edakitFilmSpecs()) edakitFilmSignature(target))
      error("PCB Film readback does not match request"))
    edakitDeliveryWriteFilms(strcat(edakitFilmSession "." nonce ".films.tsv"))
    cmd = strcat(edakitIBOMArg(edakitIBOMExe) " film-snapshot-copy --board %s --output "
      edakitIBOMArg(strcat(edakitFilmSession "." nonce ".brd")))
    result = axlRunBatchDBProgram(edakitIBOMExe cmd ?reloadDB nil
      ?startMsg "EdaKit verified Film export snapshot")
    unless(result == t error("Cannot capture Film export snapshot"))
    t))

procedure(edakitDeliveryApplyFilms(nonce)
  let((result restored fp state message)
    unless(stringp(nonce) && strlen(nonce) == 32 && rexMatchp("^[a-f0-9]+$" nonce)
      error("Invalid Film request token"))
    unless(edakitFilmBusy
      edakitFilmBusy = t
      edakitFilmBackup = nil edakitFilmMutated = nil
      result = errset(edakitFilmApplyRequest(nonce) t)
      if(result then
        state = "OK" message = "Film written and verified; save PCB to retain changes."
      else
        restored = if(edakitFilmMutated then errset(edakitFilmRestore() t) else list(t))
        state = if(restored then "ERROR" else "UNCERTAIN")
        message = if(restored then "Film update failed; original Films restored. See Allegro command log."
          else "Film rollback failed. Inspect PCB before saving or exporting."))
      when(edakitFilmSession
        fp = outfile(strcat(edakitFilmSession "." nonce ".receipt"))
        when(fp fprintf(fp "%s\n%s\n%s\n" nonce state message) close(fp)))
      edakitFilmBusy = nil
      edakitFilmBackup = nil
      axlUIWPrint(nil "%s" message))))

procedure(edakitIBOMRun(mode)
  let((cmd result source labels)
    source = axlGetDrawingName()
    if(mode == "export" || mode == "delivery" then
      if(!axlDBGetDesign() || axlIsSymbolEditor() then
        axlUIConfirm("Open a PCB board before exporting iBOM.")
        nil
      else
        labels = edakitIBOMWriteLabels(axlTempFile())
        edakitFilmSession = strcat(labels ".bridge")
        edakitFilmSource = source
        errset(edakitDeliveryWriteFilms(strcat(labels ".films.tsv")) t)
        cmd = strcat(edakitIBOMArg(edakitIBOMExe)
          " ibom-export --board %s --source " edakitIBOMArg(source)
          " --cadence-root " edakitIBOMArg(edakitIBOMRoot)
          " --labels " edakitIBOMArg(labels) " --film-session " edakitIBOMArg(edakitFilmSession)
          " --dialog --notify")
        cmd = strcat(cmd " --delivery")
        when(mode == "export" cmd = strcat(cmd " --ibom-only"))
        result = axlRunBatchDBProgram(edakitIBOMExe cmd
          ?reloadDB nil ?startMsg "EdaKit PCB snapshot for production delivery")
        axlTempFileRemove(labels)
        deleteFile(strcat(labels ".models.tsv"))
        deleteFile(strcat(labels ".films.tsv"))
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
procedure(edakitDeliveryExport() edakitIBOMRun("delivery"))
axlCmdRegister("edakit_delivery" 'edakitDeliveryExport ?cmdType "general")
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
      ("Production Delivery..." "edakit_delivery")))
)
