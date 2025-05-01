document.addEventListener('DOMContentLoaded', function() {
    // Elements
    const sourceFolderInput = document.getElementById('source-folder');
    const browseSourceButton = document.getElementById('browse-source');
    const destinationsContainer = document.getElementById('destinations-container');
    const addDestinationButton = document.getElementById('add-destination');
    const startBackupButton = document.getElementById('start-backup');

    // Naming options elements
    const appendLocationRadio = document.getElementById('append-location');
    const useSuffixRadio = document.getElementById('use-suffix');
    const dateOnlyRadio = document.getElementById('date-only');
    const folderSuffixInput = document.getElementById('folder-suffix');
    const namingOptionRadios = document.querySelectorAll('input[name="naming_option"]');

    // Panels and Progress elements
    const setupPanel = document.querySelector('.setup-panel');
    const progressPanel = document.querySelector('.progress-panel');
    const progressFill = document.querySelector('.progress-fill');
    const progressText = document.querySelector('.progress-text');
    const statusMessage = document.getElementById('status-message');
    const currentFileSpan = document.getElementById('current-file');
    const processedFilesSpan = document.getElementById('processed-files');
    const totalFilesSpan = document.getElementById('total-files');
    const processedSizeSpan = document.getElementById('processed-size');
    const totalSizeSpan = document.getElementById('total-size');
    const timeRemainingSpan = document.getElementById('time-remaining');
    const completionMessageDiv = document.querySelector('.completion-message');
    const errorMessageDiv = document.querySelector('.error-message');
    const errorTextSpan = document.getElementById('error-text');
    const newBackupButton = document.getElementById('new-backup');
    const tryAgainButton = document.getElementById('try-again'); // Renamed from 'try-again' in HTML logic

    let statusInterval = null; // To store the interval ID for polling

    // --- Initial Setup ---

    // Function to format bytes to MB/GB etc.
    function formatBytes(bytes, decimals = 1) {
        if (bytes === 0) return '0 Bytes';
        const k = 1024;
        const dm = decimals < 0 ? 0 : decimals;
        const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + ' ' + sizes[i];
    }

    // Function to add a destination row
    function addDestinationRow(folderPath = '') {
        const row = document.createElement('div');
        row.className = 'destination-row';

        row.innerHTML = `
            <div class="input-with-button">
                <input type="text" class="destination-folder" placeholder="Select destination folder" readonly>
                <button class="browse-destination">Browse</button>
            </div>
            <button class="remove-destination" aria-label="Remove destination">×</button>
        `;

        destinationsContainer.appendChild(row);
        const input = row.querySelector('.destination-folder');
        if (folderPath) {
            input.value = folderPath;
        }

        // Add event listeners to new buttons
        row.querySelector('.browse-destination').addEventListener('click', browseDestination);
        row.querySelector('.remove-destination').addEventListener('click', function() {
            destinationsContainer.removeChild(row);
            updateRemoveButtonsVisibility();
        });

        updateRemoveButtonsVisibility();
    }

    // Function to update visibility of remove buttons
    function updateRemoveButtonsVisibility() {
        const rows = destinationsContainer.querySelectorAll('.destination-row');
        rows.forEach((row, index) => {
            const removeButton = row.querySelector('.remove-destination');
            if (rows.length > 1) {
                removeButton.style.display = 'flex'; // Use flex to match CSS
            } else {
                removeButton.style.display = 'none';
            }
        });
        // Add a default row if none exist after removal
        if (rows.length === 0) {
             addDestinationRow();
        }
    }

     // Function to reset the UI to the initial setup state
    function resetUI() {
        // Stop polling if active
        if (statusInterval) {
            clearInterval(statusInterval);
            statusInterval = null;
        }

        // Show setup, hide progress
        setupPanel.style.display = 'block';
        progressPanel.style.display = 'none';
        completionMessageDiv.style.display = 'none';
        errorMessageDiv.style.display = 'none';

        // Reset progress indicators
        progressFill.style.width = '0%';
        progressText.textContent = '0%';
        statusMessage.textContent = 'Initializing...';
        currentFileSpan.textContent = '-';
        processedFilesSpan.textContent = '0';
        totalFilesSpan.textContent = '0';
        processedSizeSpan.textContent = '0 MB';
        totalSizeSpan.textContent = '0 MB';
        timeRemainingSpan.textContent = 'Calculating...';
        errorTextSpan.textContent = '';

        // Re-enable start button
        startBackupButton.disabled = false;

        // Don't clear source/destination inputs, keep config values
        // But maybe reload config in case it changed elsewhere?
        // loadConfig(); // Optional: reload config state
    }


    // --- Event Listeners ---

    browseSourceButton.addEventListener('click', function() {
        // Disable button temporarily to prevent double clicks
        browseSourceButton.disabled = true;
        fetch('/browse-source')
            .then(response => response.ok ? response.json() : Promise.reject('Network error'))
            .then(data => {
                if (data && data.path) {
                    sourceFolderInput.value = data.path;
                } else if (data && data.path === '') {
                     // User cancelled - do nothing, keep existing value
                } else {
                     console.warn("Browse source failed or returned unexpected data:", data);
                }
            })
            .catch(err => console.error('Error browsing source:', err))
            .finally(() => {
                browseSourceButton.disabled = false; // Re-enable button
            });
    });

    addDestinationButton.addEventListener('click', () => addDestinationRow());

    // Use event delegation for destination browse buttons
    destinationsContainer.addEventListener('click', function(event) {
        if (event.target.classList.contains('browse-destination')) {
            browseDestination.call(event.target); // Call browseDestination with the button as 'this'
        }
    });

    // Handler for browsing destination (needs to know which input to update)
    function browseDestination() {
        const button = this; // 'this' is the clicked button
        const input = button.closest('.destination-row').querySelector('.destination-folder');

        button.disabled = true; // Disable button temporarily

        fetch('/browse-destination')
            .then(response => response.ok ? response.json() : Promise.reject('Network error'))
            .then(data => {
                if (data && data.path) {
                    input.value = data.path;
                    // Optionally save config here if desired
                    // saveCurrentConfig();
                } else if (data && data.path === '') {
                    // User cancelled
                } else {
                    console.warn("Browse destination failed or returned unexpected data:", data);
                }
            })
            .catch(err => console.error('Error browsing destination:', err))
            .finally(() => {
                 button.disabled = false; // Re-enable button
            });
    }

    // Event listeners for naming option radio buttons
    namingOptionRadios.forEach(radio => {
        radio.addEventListener('change', handleNamingOptionChange);
    });

    function handleNamingOptionChange() {
         if (useSuffixRadio.checked) {
            folderSuffixInput.disabled = false;
            folderSuffixInput.focus();
         } else {
             folderSuffixInput.disabled = true;
             folderSuffixInput.value = ''; // Clear suffix if not used
         }
         // Maybe save config preference immediately?
         // saveCurrentConfig();
    }

    // Start Backup Button
    startBackupButton.addEventListener('click', function() {
        // Validate inputs
        const source = sourceFolderInput.value.trim();
        if (!source) {
            alert('Please select a source folder.');
            return;
        }

        const destinations = Array.from(destinationsContainer.querySelectorAll('.destination-folder'))
                                 .map(input => input.value.trim())
                                 .filter(path => path !== ''); // Get non-empty, trimmed paths

        if (destinations.length === 0) {
            alert('Please select at least one valid destination folder.');
            return;
        }

        // Determine naming options
        let appendLoc = false;
        let folderSfx = '';
        if (appendLocationRadio.checked) {
            appendLoc = true;
        } else if (useSuffixRadio.checked) {
            appendLoc = false;
            folderSfx = folderSuffixInput.value.trim();
             if (!folderSfx) {
                 alert('Please enter a custom suffix or choose another naming option.');
                 folderSuffixInput.focus();
                 return;
             }
        } else { // Date Only
             appendLoc = false;
             folderSfx = '';
        }


        // Disable button, show progress panel
        startBackupButton.disabled = true;
        setupPanel.style.display = 'none';
        progressPanel.style.display = 'block';
        completionMessageDiv.style.display = 'none';
        errorMessageDiv.style.display = 'none';
        statusMessage.textContent = 'Starting backup...';

        // Prepare data payload
        const backupData = {
            source: source,
            destinations: destinations,
            append_location: appendLoc,
            folder_suffix: folderSfx
        };

        // Start backup via POST request
        fetch('/start-backup', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Accept': 'application/json' // Expect JSON back
            },
            body: JSON.stringify(backupData)
        })
        .then(response => {
            if (!response.ok) {
                // Try to get error message from response body
                return response.json().then(errData => {
                   throw new Error(errData.message || `HTTP error! Status: ${response.status}`);
                }).catch(() => {
                   // If body cannot be parsed or no message, throw generic error
                   throw new Error(`HTTP error! Status: ${response.status}`);
                });
            }
            return response.json();
        })
        .then(data => {
            if (data.status === 'started') {
                statusMessage.textContent = 'Backup in progress...';
                // Start polling for status updates
                pollStatus();
            } else {
                 // Should not happen if response was ok, but handle defensively
                 throw new Error(data.message || 'Failed to start backup.');
            }
        })
        .catch(error => {
            console.error('Error starting backup:', error);
            statusMessage.textContent = 'Error starting backup.';
            errorTextSpan.textContent = error.message || 'Unknown error occurred.';
            errorMessageDiv.style.display = 'block';
            // Don't reset UI immediately, let user see the error
            // resetUI(); // Re-enable setup panel on error? Maybe not.
            startBackupButton.disabled = false; // Re-enable start button on error
        });
    });


    // New Backup / Try Again Buttons
    newBackupButton.addEventListener('click', resetUI);
    tryAgainButton.addEventListener('click', resetUI); // Now just resets to config screen


    // --- Status Polling and UI Update ---

    function pollStatus() {
        // Clear previous interval if any (safety check)
        if (statusInterval) clearInterval(statusInterval);

        statusInterval = setInterval(() => {
            fetch('/status')
                .then(response => {
                    if (!response.ok) { throw new Error(`Status fetch failed: ${response.status}`); }
                    return response.json();
                })
                .then(status => {
                    updateProgressUI(status);

                    // Stop polling if complete or error occurred
                    if (status.complete || status.error) {
                        clearInterval(statusInterval);
                        statusInterval = null;
                        startBackupButton.disabled = false; // Re-enable start button once done/failed

                        if (status.error) {
                             statusMessage.textContent = 'Backup failed!';
                             errorTextSpan.textContent = status.error;
                             errorMessageDiv.style.display = 'block';
                             completionMessageDiv.style.display = 'none';
                        } else if (status.complete) {
                             statusMessage.textContent = 'Backup finished!';
                             errorMessageDiv.style.display = 'none';
                             completionMessageDiv.style.display = 'block';
                        }
                    }
                })
                .catch(error => {
                    console.error('Error polling status:', error);
                    statusMessage.textContent = 'Error fetching status.';
                    // Optionally stop polling on error, or keep trying?
                    // clearInterval(statusInterval);
                    // statusInterval = null;
                    // errorTextSpan.textContent = 'Connection lost or server error.';
                    // errorMessageDiv.style.display = 'block';
                });
        }, 1000); // Poll every 1 second
    }

    function updateProgressUI(status) {
        const total = status.total_files || 0;
        const processed = status.processed_files || 0;
        const percent = total > 0 ? Math.round((processed / total) * 100) : (status.complete ? 100 : 0);

        progressFill.style.width = `${percent}%`;
        progressText.textContent = `${percent}%`;

        // Update status message based on state
        if (status.error) {
             statusMessage.textContent = 'Backup failed!';
        } else if (status.complete) {
            statusMessage.textContent = 'Backup complete!';
        } else if (processed > 0) {
             statusMessage.textContent = 'Backup in progress...';
        } else {
             statusMessage.textContent = 'Initializing...';
        }


        currentFileSpan.textContent = status.current_file || '-';
        processedFilesSpan.textContent = processed;
        totalFilesSpan.textContent = total;
        processedSizeSpan.textContent = formatBytes(status.bytes_processed || 0);
        totalSizeSpan.textContent = formatBytes(status.bytes_total || 0);
        timeRemainingSpan.textContent = status.est_time_remaining || (processed > 0 ? 'Calculating...' : '-');
    }


    // --- Load Initial Config ---
    function loadConfig() {
        fetch('/get-config')
            .then(r => r.ok ? r.json() : Promise.reject('Failed to load config'))
            .then(config => {
                sourceFolderInput.value = config.source || '';

                // Clear existing destinations and add from config
                destinationsContainer.innerHTML = ''; // Clear first
                if (config.destinations && config.destinations.length > 0) {
                    config.destinations.forEach(dest => addDestinationRow(dest));
                } else {
                    addDestinationRow(); // Add one empty row if no destinations saved
                }

                // Set naming options from config
                if (config.append_location === false) { // Explicitly false
                    if (config.folder_suffix) {
                        useSuffixRadio.checked = true;
                        folderSuffixInput.value = config.folder_suffix;
                    } else {
                        dateOnlyRadio.checked = true;
                    }
                } else { // Default or explicitly true
                    appendLocationRadio.checked = true;
                }
                handleNamingOptionChange(); // Update suffix input state based on loaded config

            })
            .catch(err => {
                console.error('Could not load config:', err);
                // Add a default destination row even if config fails
                if (destinationsContainer.children.length === 0) {
                    addDestinationRow();
                }
                handleNamingOptionChange(); // Ensure suffix disabled by default
            });
    }

    // Initial load
    loadConfig();

});