module.exports = {
    content: [
        '../templates/**/*.html',
        '../../templates/**/*.html',
        '../../**/templates/**/*.html',
        "./node_modules/flowbite/**/*.js"
    ],
    safelist: [
        'alert-success',
        'alert-error',
        'alert-warning',
        'alert-info',
        'alert-soft'
    ],
    plugins: [
        require('flowbite/plugin')
    ],
}