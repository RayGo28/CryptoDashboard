import { getCoins, getGlobalData, getCoinsSearch } from "./api.js";

document.addEventListener('alpine:init', () => {
    Alpine.data('cryptoMarket', () => ({
        coins: [],
        globalData: null,
        loading: true,
        timerId: null,
        sortColumn: 'market_cap',
        sortAsc: false,
        filter: 'all',
        page: 1,
        perPage: 10,
        searchQuery: '',
        searchResults: [],
        showDropdown: false,

        async init() {
            try {
                await this.fetchData();
                this.loading = false;
                this.scheduleNextFetch();
            } catch (error) {
                console.error('Error loading initial data:', error);
                this.loading = false;
            }
        },

        async fetchData() {
            try {

                const [coinsData, globalDataResult] = await Promise.all([
                    getCoins(this.searchQuery),
                    getGlobalData()
                ]);
                this.coins = coinsData;
                this.globalData = globalDataResult;
            } catch (error) {
                console.error("Error fetching crypto data:", error);
            }
        }, 

        async fetchSearchResults() {
            const query = this.searchQuery.trim();
            if (!query) {
                this.searchResults = [];
                this.showDropdown = false;
                return;
            }

            try {
                const data = await getCoinsSearch(query);
                this.searchResults = data.slice(0, 6);
                this.showDropdown = this.searchResults.length > 0;
            } catch (error) {
                console.error('Помилка пошуку на детальній сторінці:', error);
                this.searchResults = [];
                this.showDropdown = false;
            }
        },

        async scheduleNextFetch() {
            this.timerId = setTimeout(async () => {
                await this.fetchData();
                this.scheduleNextFetch();
            }, 5000);
        },

        sortBy(column) {
            this.page = 1;
            if(column === 'market_cap' && this.sortAsc === false){
                this.sortAsc = true;
                return;
            }
            if (this.sortColumn === column) {
                if (this.sortAsc === true) {
                    this.sortAsc = false;
                    return;
                }

                this.sortColumn = 'market_cap';
                this.sortAsc = false;
                return;
            }

            this.sortColumn = column;
            this.sortAsc = true;
        },

        get sortedCoins() {
            let result = [...this.coins];

            if (this.filter === 'gainers') {
                result = result.filter(c => (Number(c.current_data?.price_change_percentage_24h) || 0) > 0);
            } else if (this.filter === 'losers') {
                result = result.filter(c => (Number(c.current_data?.price_change_percentage_24h) || 0) < 0);
            }

            return result.sort((a, b) => {
                let aVal, bVal;

                if (this.sortColumn === 'price') {
                    aVal = Number(a.current_data?.price) || 0;
                    bVal = Number(b.current_data?.price) || 0;
                } else if (this.sortColumn === 'price_change_percentage_24h' || this.sortColumn === 'change_24h') {
                    aVal = Number(a.current_data?.price_change_percentage_24h) || 0;
                    bVal = Number(b.current_data?.price_change_percentage_24h) || 0;
                } else if (this.sortColumn === 'market_cap') {
                    aVal = Number(a.current_data?.market_cap) || 0;
                    bVal = Number(b.current_data?.market_cap) || 0;
                } else if (this.sortColumn === 'total_volume' || this.sortColumn === 'volume') {
                    aVal = Number(a.current_data?.total_volume) || 0;
                    bVal = Number(b.current_data?.total_volume) || 0;
                } else if (this.sortColumn === 'max_supply') {
                    aVal = a.max_supply ? Number(a.max_supply) : -1;
                    bVal = b.max_supply ? Number(b.max_supply) : -1;
                } else if (this.sortColumn === 'name') {
                    aVal = a.name?.toLowerCase() || '';
                    bVal = b.name?.toLowerCase() || '';
                }
                else {
                    aVal = a[this.sortColumn] ?? 0;
                    bVal = b[this.sortColumn] ?? 0;
                    if (typeof aVal === 'string') aVal = aVal.toLowerCase();
                    if (typeof bVal === 'string') bVal = bVal.toLowerCase();
                }

                if (aVal < bVal) return this.sortAsc ? -1 : 1;
                if (aVal > bVal) return this.sortAsc ? 1 : -1;
                return 0;
            });
        },

        get totalPages(){
            return Math.ceil(this.sortedCoins.length / this.perPage) || 1;
        },

        get paginatedCoins(){
            const start = (this.page - 1) * this.perPage;
            const end = start + this.perPage

            return this.sortedCoins.slice(start, end)
        },

        nextPage(){
            if(this.page < this.totalPages){
                this.page++;
            }
        },

        prevPage(){
            if(this.page > 1){
                this.page--;
            }
        },


        setFilter(type) {
            this.filter = type;
            this.page = 1;
            this.perPage = 10;

            if (type === 'all') {
                this.sortColumn = 'market_cap';
                this.sortAsc = false;
            } else if (type === 'gainers') {
                this.sortColumn = 'price_change_percentage_24h';
                this.sortAsc = false;
            } else if (type === 'losers') {
                this.sortColumn = 'price_change_percentage_24h';
                this.sortAsc = true;
            }
        },

        destroy() {
            if (this.timerId) clearTimeout(this.timerId);
        },

        priceFormat(val) {
            if (val == null) return '$0.00';
            return new Intl.NumberFormat('en-US', {
                style: 'currency',
                currency: 'USD',
                minimumFractionDigits: 2,
                maximumFractionDigits: val < 1 ? 8 : 2
            }).format(val);
        },

        usdFormat(val) {
            if (val == null) return '$0';
            return new Intl.NumberFormat('en-US', {
                style: 'currency',
                currency: 'USD',
                notation: 'compact',
                maximumFractionDigits: 2
            }).format(val);
        },

        percentFormat(val) {
            if (val == null) return '0.00%';
            const prefix = val >= 0 ? '+' : '';
            return prefix + new Intl.NumberFormat('en-US', {
                minimumFractionDigits: 2,
                maximumFractionDigits: 2
            }).format(val) + '%';
        },

        numberFormat(val) {
            if (val == null) return '0';
            return new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 }).format(val);
        }
    })); 
});