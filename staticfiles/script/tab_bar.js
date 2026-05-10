    function switchTab(btn, targetId) {
        // Reset buttons
        document.querySelectorAll('.tab-btn').forEach(b => {
            b.classList.remove('bg-white', 'text-gray-900', 'shadow-sm');
            b.classList.add('text-gray-500', 'hover:bg-base-300');
        });
        
        // Active button
        btn.classList.add('bg-white', 'text-gray-900', 'shadow-sm');
        btn.classList.remove('text-gray-500', 'hover:bg-base-300');
        
        // Hide all panels
        document.querySelectorAll('.tab-panel').forEach(p => {
            p.classList.add('hidden');
            p.classList.remove('block');
        });
        
        // Show target panel
        const target = document.getElementById(targetId);
        if (target) {
            target.classList.remove('hidden');
            target.classList.add('block');
        }
    }