(function () {
  const areas = window.SUBMISSION_AREAS || [];
  const areaState = {}; // key -> { files: File[], declared: bool }

  areas.forEach(a => { areaState[a.key] = { files: [], declared: false }; });

  function humanSize(bytes) {
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
    return (bytes / (1024 * 1024)).toFixed(1) + " MB";
  }

  function extOf(filename) {
    const idx = filename.lastIndexOf(".");
    return idx === -1 ? "" : filename.slice(idx).toLowerCase();
  }

  function validateClientSide(area, file) {
    if (!area.allowed_extensions.map(e => e.toLowerCase()).includes(extOf(file.name))) {
      return `'${file.name}' is not an allowed file type for ${area.label}.`;
    }
    if (file.size > area.max_size_mb * 1024 * 1024) {
      return `'${file.name}' exceeds the ${area.max_size_mb}MB limit for ${area.label}.`;
    }
    if (file.size === 0) {
      return `'${file.name}' is empty.`;
    }
    return null;
  }

  function renderFileList(area) {
    const listEl = document.querySelector(`[data-area-list="${area.key}"]`);
    listEl.innerHTML = "";
    areaState[area.key].files.forEach((file, idx) => {
      const chip = document.createElement("div");
      chip.className = "file-chip";
      chip.innerHTML = `<span>${file.name} &middot; ${humanSize(file.size)}</span>`;
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "remove";
      btn.textContent = "Remove";
      btn.addEventListener("click", () => {
        areaState[area.key].files.splice(idx, 1);
        renderFileList(area);
      });
      chip.appendChild(btn);
      listEl.appendChild(chip);
    });
  }

  function setDeclared(area, declared) {
    const state = areaState[area.key];
    const checkbox = document.querySelector(`.declare-checkbox[data-declare="${area.key}"]`);
    const zone = document.querySelector(`.dropzone[data-area="${area.key}"]`);

    state.declared = declared;
    checkbox.checked = declared;
    zone.classList.toggle("disabled", declared);

    if (declared) {
      // Declaring "not submitted" clears any files already chosen for this area.
      state.files = [];
      renderFileList(area);
    }
  }

  function addFiles(area, fileList) {
    const incoming = Array.from(fileList);
    const errors = [];
    const state = areaState[area.key];

    if (state.declared) {
      // Attaching a file supersedes an earlier "not submitted" declaration.
      setDeclared(area, false);
    }

    for (const file of incoming) {
      const err = validateClientSide(area, file);
      if (err) { errors.push(err); continue; }

      if (state.files.length >= area.max_files) {
        if (area.max_files === 1) {
          state.files = [file]; // replace single-slot area
        } else {
          errors.push(`Only ${area.max_files} file(s) allowed for ${area.label}.`);
          continue;
        }
      } else {
        state.files.push(file);
      }
    }

    renderFileList(area);
    if (errors.length) showErrors(errors);
  }

  function showErrors(errors) {
    const box = document.getElementById("error-box");
    box.style.display = "block";
    box.innerHTML = "<strong>Please fix the following:</strong><ul>" +
      errors.map(e => `<li>${e}</li>`).join("") + "</ul>";
    box.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  function clearErrors() {
    const box = document.getElementById("error-box");
    box.style.display = "none";
    box.innerHTML = "";
  }

  // Wire up each dropzone + its declaration checkbox
  areas.forEach(area => {
    const zone = document.querySelector(`.dropzone[data-area="${area.key}"]`);
    const input = zone.querySelector('input[type="file"]');
    const checkbox = document.querySelector(`.declare-checkbox[data-declare="${area.key}"]`);

    zone.addEventListener("click", () => {
      if (!areaState[area.key].declared) input.click();
    });
    input.addEventListener("change", () => {
      addFiles(area, input.files);
      input.value = ""; // allow re-selecting the same file
    });

    checkbox.addEventListener("change", () => {
      setDeclared(area, checkbox.checked);
    });

    ["dragenter", "dragover"].forEach(evt => {
      zone.addEventListener(evt, (e) => {
        e.preventDefault();
        if (!areaState[area.key].declared) zone.classList.add("dragover");
      });
    });
    ["dragleave", "drop"].forEach(evt => {
      zone.addEventListener(evt, (e) => {
        e.preventDefault();
        zone.classList.remove("dragover");
      });
    });
    zone.addEventListener("drop", (e) => {
      if (areaState[area.key].declared) return;
      if (e.dataTransfer.files && e.dataTransfer.files.length) {
        addFiles(area, e.dataTransfer.files);
      }
    });
  });

  // Submit
  const form = document.getElementById("submit-form");
  const submitBtn = document.getElementById("submit-btn");
  const progressTrack = document.getElementById("progress-track");
  const progressFill = document.getElementById("progress-fill");

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    clearErrors();

    const name = document.getElementById("name").value.trim();
    const studentId = document.getElementById("student_id").value.trim();
    const email = document.getElementById("email").value.trim();

    const errors = [];
    if (!name) errors.push("Name is required.");
    if (!studentId) errors.push("Student ID is required.");
    if (!email) errors.push("Email is required.");
    areas.forEach(area => {
      const state = areaState[area.key];
      if (!state.declared && state.files.length === 0) {
        errors.push(`Please attach a file for '${area.label}', or tick the box confirming you did not submit it.`);
      }
    });

    if (errors.length) { showErrors(errors); return; }

    const formData = new FormData();
    formData.append("name", name);
    formData.append("student_id", studentId);
    formData.append("email", email);
    areas.forEach(area => {
      const state = areaState[area.key];
      formData.append(`${area.key}_declared`, state.declared ? "true" : "false");
      state.files.forEach(file => formData.append(area.key, file));
    });

    submitBtn.disabled = true;
    submitBtn.textContent = "Submitting\u2026";
    progressTrack.style.display = "block";

    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/submit");

    xhr.upload.addEventListener("progress", (e) => {
      if (e.lengthComputable) {
        const pct = Math.round((e.loaded / e.total) * 100);
        progressFill.style.width = pct + "%";
      }
    });

    xhr.onload = () => {
      submitBtn.disabled = false;
      submitBtn.textContent = "Submit";
      let data;
      try { data = JSON.parse(xhr.responseText); } catch (err) { data = null; }

      if (xhr.status === 200 && data && data.ok) {
        document.getElementById("form-card").style.display = "none";
        document.getElementById("result-card").style.display = "block";
        document.getElementById("result-code").textContent = data.code;
        let meta = data.email_sent
          ? "A confirmation email has also been sent to you."
          : "We could not send a confirmation email \u2014 please save this code.";
        if (data.storage_note) meta += " " + data.storage_note;
        document.getElementById("result-meta").textContent = meta;
      } else if (data && data.errors) {
        showErrors(data.errors);
      } else {
        showErrors(["Something went wrong submitting your files. Please try again."]);
      }
    };

    xhr.onerror = () => {
      submitBtn.disabled = false;
      submitBtn.textContent = "Submit";
      showErrors(["Network error \u2014 please check your connection and try again."]);
    };

    xhr.send(formData);
  });
})();
